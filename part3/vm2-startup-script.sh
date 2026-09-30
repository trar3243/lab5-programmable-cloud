#!/bin/bash
# send everything this script prints to one log, so debugging is just
#   cat /var/log/startup-script.log
exec > /var/log/startup-script.log 2>&1

# never prompt -- there is nobody here to answer the needrestart dialog
export DEBIAN_FRONTEND=noninteractive

# the script starts in /, so make somewhere to work and go there
mkdir -p /srv/app
cd /srv/app/

apt-get update
apt-get install -y python3 python3-pip git

git clone https://github.com/cu-csci-4253-datacenter/flask-tutorial
cd flask-tutorial

python3 setup.py install
pip3 install -e .

export FLASK_APP=flaskr
flask init-db

# nohup keeps flask alive after this script exits
nohup flask run -h 0.0.0.0 &
