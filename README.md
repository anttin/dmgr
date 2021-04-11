# dmgr - Daemon Manager

This program will:

- Start a daemon process
- Read the daemon's master process pid from a file
- Makes sure daemon process name matches expected
- Keep track of the state of the process
- Intercept signals and pass them as commands
- Exit when the daemon process exits

It is useful for running daemon applications in containers, with or without supervisord.

## Install

Clone the repository and install the module dependencies.

```bash
# Clone repository
git clone https://github.com/anttin/dmgr.git dmgr
cd dmgr

# optionally create and activate virtual environment
python3 -m venv venv-dmgr
source venv-dmgr/bin/activate

# install dependencies
python3 -m pip install -r requirements.txt
```

## Usage

```shell
USAGE: python3 dmgr.py \ 
    [-h|--help] \
     -n|--name        <main-process-name> \
     -p|--pidfile     <path-to-pidfile> \
     -c|--cmdstart    <start-command> \
     -C|--cmdstop     <stop-command> \
    [-w|--waitstart   <seconds-to-wait-for-process-to-start>] \
    [-W|--waitstop    <seconds-to-wait-for-process-to-stop>] \
    [-s|--signalcmds  <SIGNAL1="command,parameter1,parameter2";...;SIGNALn="...">] \
    [-W|--waitstop    <seconds-to-wait-for-process-to-stop>] \
    [-l|--loglevel    <loglevel>] \
```

`main-process-name` is the name of the daemon's master process, e.g. `master` for postfix.

`path-to-pidfile` is the file path to the daemon's pid file, e.g. `/var/spool/postfix/pid/master.pid`.

`start-command` is the command used to start the daemon process.  Use commas to separate parameters, e.g. `--cmdstart="/usr/sbin/postfix,start"`. Default is 10.

`stop-command` is the command used to stop the daemon process.  Use commas to separate parameters. Default is 10.

`seconds-to-wait-for-process-to-start` is an integer that sets how many seconds the program will wait for the daemon to start properly. This value is also used for waiting commands to finish during state transitions.

`seconds-to-wait-for-process-to-stop` is an integer that sets how many seconds the program will wait for the daemon to stop properly.

`signalcmds` is a semicolon separated list of key-value-pairs, where the key is the name (or integer value) of the signal (e.g. `SIGHUP` or `1`) and the value is the command to execute when the signal is caught.

`passthrough` is a semicolon separated list of key-value-pairs, where the key is the name (or integer value) of the signal (e.g. `SIGHUP` or `1`) to listen, and the value is the name of the signal to pass for the daemon provess. The value can be omitted if it is the same as the key.

`loglevel` is the logging level. Default is `INFO`.
