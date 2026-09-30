#!/usr/bin/env python3

import argparse
import os
import time
from pprint import pprint

import googleapiclient.discovery
import google.auth
import google.oauth2.service_account as service_account

# read files relative to this script, not the current directory, so this
# works no matter where it is launched from
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))

#
# Use Google Service Account - See https://google-auth.readthedocs.io/en/latest/reference/google.oauth2.service_account.html#module-google.oauth2.service_account
#
credentials = service_account.Credentials.from_service_account_file(
    filename=os.path.join(SCRIPT_DIR, 'service-credentials.json'))
project = 'csci-5253-lab5-trar3243'
service = googleapiclient.discovery.build('compute', 'v1', credentials=credentials)
ZONE = 'us-west1-b'
INSTANCE_NAME = "troys-vm-first"

#
# VM-1's startup script. It runs as root on VM-1 at boot, with no terminal
# attached. VM-1 starts out empty, so this pulls the files part3.py attached
# as metadata down onto disk, installs the Google API libraries, and runs
# launch_vm2.py to create VM-2. The metadata keys curl'd here must match the
# keys in create_instance() below, or curl silently writes an empty file.
# The shebang must be the very first characters of the string.
#
vm1_startup_script = """#!/bin/bash
# send everything this script prints to one log, so debugging is just
#   cat /var/log/startup-script.log
exec > /var/log/startup-script.log 2>&1

# never prompt -- there is nobody here to answer the needrestart dialog
export DEBIAN_FRONTEND=noninteractive

apt-get update
apt-get install -y python3 python3-pip

# launch_vm2.py expects its files in the same directory as itself
mkdir -p /srv
cd /srv

MD=http://metadata/computeMetadata/v1/instance/attributes
H="Metadata-Flavor: Google"
curl -s $MD/vm1-launch-vm2-code -H "$H" > launch_vm2.py
curl -s $MD/vm2-startup-script  -H "$H" > vm2-startup-script.sh
curl -s $MD/service-credentials -H "$H" > service-credentials.json

pip3 install google-api-python-client google-auth
python3 ./launch_vm2.py
"""

def read_file(name):
    with open(os.path.join(SCRIPT_DIR, name)) as f:
        return f.read()

#
# The config dict below is adapted from Google's Compute Engine Python sample,
# compute/api/create_instance.py in GoogleCloudPlatform/python-docs-samples.
#
def create_instance(compute, project, zone, name):
    image_response = compute.images().getFromFamily(
        project='ubuntu-os-cloud', family='ubuntu-2204-lts'
    ).execute()

    machine_type = f'zones/{zone}/machineTypes/e2-micro'
    config = {
        'name': name,
        'machineType': machine_type,

        'disks': [
            {
                'boot': True,
                'autoDelete': True,
                'initializeParams': {'sourceImage': image_response['selfLink']}
            }
        ],

        # VM-1 needs a public IP to reach apt and pip, but no firewall tag --
        # nothing connects to it, it only makes outbound calls
        'networkInterfaces': [
            {
                'network': 'global/networks/default',
                'accessConfigs': [
                    {'type': 'ONE_TO_ONE_NAT', 'name': 'External NAT'}
                ]
            }
        ],

        # 'startup-script' is the only key the guest agent runs automatically;
        # the others are just data that vm1_startup_script fetches with curl
        'metadata': {
            'items': [
                {'key': 'startup-script', 'value': vm1_startup_script},
                {'key': 'vm1-launch-vm2-code', 'value': read_file('launch_vm2.py')},
                {'key': 'vm2-startup-script', 'value': read_file('vm2-startup-script.sh')},
                {'key': 'service-credentials', 'value': read_file('service-credentials.json')},
            ]
        },
    }

    return compute.instances().insert(
        project=project,
        zone=zone,
        body=config
    ).execute()

#
# Adapted from wait_for_operation() in Google's compute/api/create_instance.py
# sample (GoogleCloudPlatform/python-docs-samples).
#
def wait_for_operation(compute, project, zone, operation):
    print(f'Waiting for operation {operation} to finish...')
    while True:
        result = compute.zoneOperations().get(
            project=project,
            zone=zone,
            operation=operation).execute()

        if result['status'] == 'DONE':
            print("...done.")
            # a DONE operation can still have failed, so check before returning
            if 'error' in result:
                raise Exception(result['error'])
            return result

        time.sleep(1)

def list_instances(compute, project, zone):
    result = compute.instances().list(project=project, zone=zone).execute()
    # return an empty list rather than None when the zone has no instances,
    # so callers can always iterate the result
    return result['items'] if 'items' in result else []

def main():
    op = create_instance(service, project, ZONE, INSTANCE_NAME)
    wait_for_operation(service, project, ZONE, op['name'])

    print("Your running instances are:")
    for instance in list_instances(service, project, ZONE):
        print(instance['name'])

    # to debug VM-1: gcloud compute ssh troys-vm-first --zone=us-west1-b
    #   then: cat /var/log/startup-script.log, and look in /srv
    print(f"{INSTANCE_NAME} is up. In a few minutes it should create VM-2; "
          f"check with: gcloud compute instances list")

if __name__ == "__main__":
    main()
