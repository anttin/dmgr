#!/bin/sh
if [ "$1" == "start" ]; then
  echo "starting"
  if [ -z "$2" ]; then
    T=120
  else
    T=$2
  fi 
  sleep $T &
  PID=$!
  echo $PID >pid.txt
  echo "started $PID" 

elif [ "$1" == "stop" ]; then
  echo "stopping"
  PID=$(cat pid.txt)
  LST=$(pgrep sleep)
  for P in $LST; do
    echo $PID $P
    if [ "$PID" == "$P" ]; then 
      echo "terminate it" 
      kill $PID
      break
    fi
  done
else
  echo "command missing"
fi
echo "end"
