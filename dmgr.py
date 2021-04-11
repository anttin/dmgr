import datetime
import logging
import logging.handlers
import psutil
import queue
import signal
import subprocess
import sys
import time

from anoptions import Parameter, Options
from enum import Enum

class ExpectedOutcome(Enum):
  PROCESS_RUNNING = 1
  PROCESS_STOPPED = 2


class DaemonManager(object):
  def __init__(self, config, logger):
    self.pidfile = config["pidfile"]
    self.processname = config["processname"].lower()

    self.config = config
    self.logger = logger

    self.signal_queue = queue.Queue()
    self.signal_commands = {}
    self.exit_signals = [ signal.SIGINT, signal.SIGTERM ]

    self.check_if_already_running()
    self.process_config()


  @staticmethod
  def get_process(pid):
    # Will return psutil.Process for pid, and None if pid is not found
    try:
      p = psutil.Process(pid)
      return p
    except psutil.NoSuchProcess:
      return None  


  @staticmethod
  def file_exists(filename):
    import os
    return filename is not None and os.path.exists(filename) and os.path.isfile(filename)  


  @staticmethod
  def load_text(filename):
    result = None
    if filename == '-':
      import sys
      f = sys.stdin
    else:
      f = open(filename, 'r', encoding='utf8')
    with f as file:
      result = file.read()
    return result


  @staticmethod
  def is_proc_running(proc):
    # Will return True if psutil.Process is running
    try:
      if proc.is_running() is True and proc.status() != psutil.STATUS_ZOMBIE:
        return True
    except (psutil.NoSuchProcess):
      pass
    return False


  @staticmethod
  def start_subprocess(command_string, **kwargs):
    # Starts and returns a subprocess
    try: 
      subproc = subprocess.Popen(command_string.split(","), **kwargs)
    except FileNotFoundError:
      return None
    return subproc


  def run_cmd_and_wait(self, cmd, pidfile, waittime, expected_outcome):
    if self.file_exists(pidfile):
      old_pid = int(self.load_text(pidfile).strip())
    else:
      old_pid = None

    dttimeout = datetime.datetime.now()+datetime.timedelta(seconds=waittime)

    proc = None
    new_pid = None
    
    # Run the command (if we have one), None is an option here too
    # to enable checking an already started transition
    if cmd is not None:
      cmd_subproc = self.start_subprocess(cmd, stdout=sys.stdout)
      if cmd_subproc is None:
        return False
      cmd_proc = self.get_process(cmd_subproc.pid)
    else:
      cmd_subproc = None
      cmd_proc = None

    # Wait for process to transition
    while datetime.datetime.now() < dttimeout:

      if expected_outcome == ExpectedOutcome.PROCESS_RUNNING:
        r = cmd_subproc.poll()

        # Look for a new pid in pidfile in case of restart
        if new_pid is None and self.file_exists(pidfile):
          pid = int(self.load_text(pidfile).strip())
          if pid != old_pid or r is not None:
            new_pid = pid

      elif expected_outcome == ExpectedOutcome.PROCESS_STOPPED:
        proc = self.get_process(old_pid)
        if proc is None:
          # Process is stopped
          break

      # Look for new process if we have the pid
      if new_pid is not None:
        proc = self.get_process(new_pid)
        if proc is not None:
          # Got the new process running
          break

      time.sleep(0.5)

    # Check for timeout
    if datetime.datetime.now() >= dttimeout:
      return False

    pid = None
 
    while datetime.datetime.now() < dttimeout:
      if expected_outcome == ExpectedOutcome.PROCESS_RUNNING:
        # Make sure process is running until "timeout"
        if pid is None:
          pid = int(self.load_text(pidfile).strip())

        proc = self.get_process(old_pid)
        if proc is None:
          # Process is not running
          return False

      else:
        if self.is_proc_running(cmd_proc) is False:
          break

      time.sleep(0.5)

    # Ensure command process is or will be exited
    if cmd_subproc is not None:
      if self.is_proc_running(cmd_proc) is True:
        self.logger.info("Command process is still running, sending SIGTERM")
        cmd_subproc.terminate()
        cmd_subproc.wait(timeout=3)
      if self.is_proc_running(cmd_proc) is True:
        self.logger.info("Command process is still running, sending SIGKILL")
        cmd_subproc.kill()    

    # We should know the outcome for a stopping process at this time
    if expected_outcome == ExpectedOutcome.PROCESS_STOPPED:
      proc = self.get_process(old_pid)
      return (proc is None)

    # Transition finished succesfully
    return True


  ##################################################################################


  def signal_handler(self, signum, frame):
    sig = signal.Signals(signum)
    self.logger.info('Signal {} detected'.format(sig.name))
    self.signal_queue.put_nowait((sig, frame))


  def get_pid_info(self):
    if self.file_exists(self.pidfile):
      pid = int(self.load_text(self.pidfile).strip())
      return self.get_process(pid)
    else:
      return None


  def check_if_already_running(self):
    if self.file_exists(self.pidfile):
      p = self.get_pid_info()
      if p is not None:
        if p.name().lower() == self.processname:
          self.logger.info("Process in pidfile is already running -- exiting")
          sys.exit(1)
      import os
      os.remove(self.pidfile)
      self.logger.info("Removed old pidfile")


  def process_config(self):
    self.signal_lookup = {}
    # Collect all valid signals into a lookup dict
    for x in signal.valid_signals():
      try:
        self.signal_lookup[x.name] = x
        self.signal_lookup[str(x.value)] = x
      except AttributeError:
        self.signal_lookup[str(x)] = x

    # Parse passthrough-input for signal passthrough mappings
    self.passthroughmap = {}
    if "passthrough" in self.config:
      for x in self.config["passthrough"].split(';'):
        y = x.split('=')
        if len(y) not in (1, 2):
          self.logger.critical("Invalid signal passthrough configuration (syntax) -- exiting")
          sys.exit(1)
        if len(y) == 1:
          y.append(y[0]) 
        sig_in, sig_out = y
        if sig_in in self.signal_lookup and sig_out in signal_lookup:
          self.passthroughmap[self.signal_lookup[sig_in]] = self.signal_lookup[sig_out]
        else:
          self.logger.critical("Invalid signal passthrough configuration (unknown signal) -- exiting")
        if self.signal_lookup[sig_in] == signal.SIGINT:
          self.exit_signals.remove(signal.SIGINT)
          self.logger.warn("Passthrough for SIGINT defined -- you will not be able to stop this program with Ctrl-C".format(sig_in))  

    if "stopcmd" in self.config:
      for sig in (signal.SIGTERM, signal.SIGINT):
        if sig not in self.passthroughmap.keys():
          self.signal_commands[sig] = self.config["stopcmd"] 
        else:
          self.logger.info("Passthrough for {} defined together with stopcmd -- will use passthrough".format(sig)) 

    # Parse input for signals
    if "signals" in self.config:
      for x in self.config["signals"].split(';'):
        y = x.split('=')
        if len(y) != 2:
          self.logger.critical("Invalid signal configuration -- exiting")
          sys.exit(1)
    
        sig, cmd = y
        if sig in self.signal_lookup:
          if self.signal_lookup[sig] in (signal.SIGKILL, signal.SIGTSTP):
            self.logger.critical("Impossible to hook to signal {} -- exiting".format(sig)) 
            sys.exit(1)
          if self.signal_lookup[sig] == signal.SIGTERM and "stopcmd" in d:
            self.logger.warn("Both stopcmd and signalcmd for {} defined -- will use stopcmd".format(sig)) 
            continue
          if self.signal_lookup[sig] == signal.SIGINT:
            exit_signals.remove(signal.SIGINT)
            self.logger.warn("Command for SIGINT defined -- you will not be able to stop this program with Ctrl-C".format(sig)) 
          if self.signal_lookup[sig] in self.passthroughmap.keys():
            self.logger.warn("Both passthrough and signalcmd for {} defined -- will use passthrough".format(sig))
            continue 
          self.signal_commands[self.signal_lookup[sig]] = cmd
        else:
          self.logger.critical("Unknown signal {} -- exiting".format(sig))  
          sys.exit(1)

      # Register signals
      for sig, cmd in self.signal_commands.items():
        signal.signal(sig, self.signal_handler)
        self.logger.info("Registered signal {} with command '{}'".format(sig.name, cmd))

      # Register passthrough mappings
      for sig_in, sig_out in self.passthroughmap.items():
        signal.signal(sig_in, self.signal_handler)
        self.logger.info("Registered signal {} with passthrough using signal {}".format(sig_in.name, sig_out.name))

  def run(self):
    self.logger.info("Starting process")
    status = self.run_cmd_and_wait(
      self.config["startcmd"],
      self.pidfile,
      self.config["waitstart"],
      ExpectedOutcome.PROCESS_RUNNING
    )
  
    if status is True:
      self.logger.info("Process is running after {} seconds".format(self.config["waitstart"]))
    else:
      self.logger.critical("Failed to start process -- exiting")
      sys.exit(1)

    class StartExit(Exception):
      def __init__(self, cmd):
        self.cmd = cmd

    main_pid  = None
    main_proc = None
    stopcmd   = None
    try:
      while True:
        try:
          sig, frame = self.signal_queue.get(block=True, timeout=1)

          # Got a signal within the queue get timeout limits, let's process it
          if sig in self.passthroughmap.keys():
            self.logger.info("Passthrough signal as {}".format(self.passthroughmap[sig].name))
            effective_signal = self.passthroughmap[sig]
            main_proc.send_signal(effective_signal)
            excmd = None
          else:
            effective_signal = sig
            excmd = self.signal_commands[sig]
            self.logger.info("Run command: {}".format(excmd))

          if effective_signal in self.exit_signals:
            raise StartExit(excmd)

          if excmd is not None:
            status = self.run_cmd_and_wait(
              excmd, 
              self.pidfile,
              self.config["waitstart"],
              ExpectedOutcome.PROCESS_RUNNING
            )

            if status is False:
              self.logger.critical("Command failed -- exiting")
              sys.exit(1)
          
          # Reset the main_pid to ensure that we refresh the process information
          main_pid = None

        except queue.Empty:
          # No new signals
          pass

        # Update pid and proc variables of the main process for the checker if needed
        if main_pid is None:
          main_pid = int(self.load_text(self.pidfile).strip())
          main_proc = None
        if main_proc is None:
          main_proc = self.get_process(main_pid)

        # Here we check that our main process is still running
        if self.is_proc_running(main_proc) is False:
          self.logger.critical("Process exited unexpectedly")
          sys.exit(1)

    except (KeyboardInterrupt, StartExit) as e:
      # We'll break out ouf the loop and continue with the soft exit procedure
      self.logger.info("Start exit procedure")
      if isinstance(e, StartExit):
        stopcmd = e.cmd
      elif "stopcmd" in self.config:
        stopcmd = self.config["stopcmd"] 


    # Exit process; exit zero if all is ok and 1 if not

    status = self.run_cmd_and_wait(
      stopcmd, 
      self.pidfile,
      self.config["waitstop"],
      ExpectedOutcome.PROCESS_STOPPED
    )

    if status is False:
      self.logger.critical("Failed to end the process -- exiting")
      if main_proc is not None:
        main_proc.send_signal(signal.SIGTERM)
      sys.exit(1)

    # Process ended ok
    self.logger.info("Done.")
    return  


######################################################


def usage():
  print("USAGE: python3 dmgr.py [-h|--help] \\")
  print("     -n|--name        <main-process-name> \\")
  print("     -p|--pidfile     <path-to-pidfile> \\")
  print("     -c|--cmdstart    <start-command> \\")
  print("     -C|--cmdstop     <stop-command> \\")
  print("    [-w|--waitstart   <seconds-to-wait-for-process-to-start>] \\")
  print("    [-W|--waitstop    <seconds-to-wait-for-process-to-stop>] \\")
  print("    [-s|--signalcmds  <SIGNAL1=\"command,parameter1,parameter2\";...;SIGNALn=\"...\">] \\")
  print("    [-S|--passthrough <SIGNAL1[=OTHERSIGNAL];..;SIGNALn>]")
  sys.exit(1)


def main(argv):
  parameters = [
    Parameter("name",        str, "processname"),
    Parameter("cmdstart",    str, "startcmd",    short_name='c'),
    Parameter("cmdstop",     str, "stopcmd",     short_name='C'),
    Parameter("waitstart",   int, "waitstart",   short_name='w', default=10),
    Parameter("waitstop",    int, "waitstop",    short_name='W', default=10),
    Parameter("pidfile",     str, "pidfile"),
    Parameter("signalcmds",  str, "signals"),
    Parameter("passthrough", str, "passthrough", short_name='S'),
    Parameter("help", Parameter.flag, "help"),
    Parameter("loglevel",    str, "loglevel",    default='INFO')
  ]

  opt = Options(parameters, argv, "dmgr")
  config = opt.eval()

  if config["help"] is True:
    usage()

  required = [ "processname", "startcmd", "pidfile" ]
  for x in required:
    if x not in config:
      usage()

  logging.basicConfig(format="%(asctime)-15s %(name)s %(levelname)s %(message)s")
  logger = logging.getLogger("dmgr")
  logger.setLevel(config["loglevel"])

  import os
  if os.path.exists("/dev/log"):
    handler = logging.handlers.SysLogHandler(address="/dev/log")
    logger.addHandler(handler)

  o = DaemonManager(config, logger)
  o.run()

  # If all is well, we'll end with exit code 0


if __name__ == "__main__":
  main(sys.argv[1:])
