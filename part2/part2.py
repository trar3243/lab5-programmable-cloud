#!/usr/bin/env python3

import argparse
import os
import sys 
import time
from pprint import pprint
import googleapiclient.discovery
import google.auth

parent_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.append(parent_dir)
from part1.part1 import create_instance, wait_for_operation, get_ip

credentials, project = google.auth.default()
service = googleapiclient.discovery.build('compute', 'v1', credentials=credentials)

ZONE = 'us-west1-b'
INSTANCE_NAME = "troys-vm"
FIREWALL_RULE = 'allow-5000'
NETWORK_TAG = 'allow-5000'

#
# Stub code - just lists all instances
#
def list_instances(compute, project, zone):
    result = compute.instances().list(project=project, zone=zone).execute()
    return result['items'] if 'items' in result else []

def create_snapshot(compute, snapshot_name, project, zone, disk):
    # look at https://docs.cloud.google.com/compute/docs/reference/rest/v1/disks/createSnapshot#request-body
    # shows 'name' as required field in the request body 
    request_body = {
        "name": snapshot_name,
        "description": "A snapshot made through the API"
    }

    # in the documentation, we have POST https://compute.googleapis.com/compute/v1/projects/{project}/zones/{zone}/disks/{disk}/createSnapshot
    # this shows project, zone, and disk as input parameters 
    request = compute.disks().createSnapshot(
        project = project,
        zone=zone,
        disk=disk,
        body = request_body 
    )

    response = request.execute()
    return response 

new_startup_thing = """#!/bin/bash
# send everything this script prints to one log, so debugging is just
#   cat /var/log/startup-script.log
exec > /var/log/startup-script.log 2>&1

# never prompt -- there is nobody here to answer the needrestart dialog
export DEBIAN_FRONTEND=noninteractive

cd /srv/app/flask-tutorial

export FLASK_APP=flaskr

# nohup keeps flask alive after this script exits
nohup flask run -h 0.0.0.0 &
"""
def main():
    instance = service.instances().get(
        project=project,
        zone=ZONE,
        instance=INSTANCE_NAME
    ).execute()
    # 'source' is a full URL ending in .../disks/<disk-name>; keep just the name
    disk_name = instance['disks'][0]['source'].rsplit('/', 1)[-1]
    print(f"Disk Name is: {disk_name}")

    snapshot_name = f"base-snapshot-{INSTANCE_NAME}"
    snapshot_op = create_snapshot(service, snapshot_name, project, ZONE, disk_name)
    print("Waiting for snapshot creation operation...")
    wait_for_operation(service, project, ZONE, snapshot_op['name'])

    # okay, now we need to create new instances. These will be clones based on the snapshot. 
    # time from insert() until reports the instance created (not until
    # flask is serving)
    clone_names = []
    timings = []
    for i in range(3):
        curr_instance_name = f"troys-vm-v{i}"
        start = time.time()
        op=create_instance(
            service,
            project,
            ZONE,
            curr_instance_name,
            f"global/snapshots/{snapshot_name}",
            new_startup_thing, # dont need to install flask or init the db
            # tags belong to the VM, not its disk, so the snapshot doesn't
            # carry troys-vm's allow-5000 tag over -- the clones start with
            # none. Without it the allow-5000 firewall rule (from part1)
            # doesn't apply and port 5000 stays blocked. Setting it at
            # creation skips the separate setTags call part1 makes.
            [NETWORK_TAG]
        )
        print(f"Started create for instance {curr_instance_name}. Timing create...")
        wait_for_operation(service, project, ZONE, op['name'])
        elapsed = time.time() - start
        print(f"{curr_instance_name} took {elapsed:.2f}s to create")
        clone_names.append(curr_instance_name)
        timings.append(elapsed)

    print("Your running instances are:")
    for instance in list_instances(service, project, 'us-west1-b'):
        print(instance['name'])

    print("\nCreation times (for TIMING.md):")
    for name, elapsed in zip(clone_names, timings):
        print(f"| {name} | {elapsed:.2f}s |")

    print("\nThe clones will be available at (may take a minute to start up):")
    for name in clone_names:
        ip = get_ip(service, project, ZONE, name)
        print(f"  {name}: http://{ip}:5000")

    print("\nTo clean up the snapshot and cloned instances, run:")
    print(f"  gcloud compute instances delete {' '.join(clone_names)} --zone={ZONE} --quiet")
    print(f"  gcloud compute snapshots delete {snapshot_name} --quiet")

if __name__ == "__main__":
    main() 
