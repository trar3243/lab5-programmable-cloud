#!/usr/bin/env python3

import argparse
import os
import time
from pprint import pprint
import google.oauth2.service_account as service_account

import googleapiclient.discovery
import google.auth

credentials = service_account.Credentials.from_service_account_file('service-credentials.json')
project = 'csci-5253-lab5-trar3243'
service = googleapiclient.discovery.build('compute', 'v1', credentials=credentials)
ZONE = 'us-west1-b'
INSTANCE_NAME = "troys-vm-second"
FIREWALL_RULE = 'allow-5000'
NETWORK_TAG = 'allow-5000'

#
# VM-2's startup script. It runs as root on VM-2 at boot, with no terminal
# attached. Read it from the file next to this script rather than the current
# directory, so this works no matter where it is launched from.
#
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
with open(os.path.join(SCRIPT_DIR, 'vm2-startup-script.sh')) as f:
    startup_thing = f.read()

#
# The config dict below is adapted from Google's Compute Engine Python sample,
# compute/api/create_instance.py in GoogleCloudPlatform/python-docs-samples.
#
def create_instance(
        compute,
        project,
        zone,
        name,
        source_disk_image_override = None,
        startup_script = startup_thing,
        network_tags = None
    ):

    # first, pick the boot disk source. with an override we boot from that
    # snapshot; otherwise look up the latest Ubuntu image, comparable to the
    # google tutorial's get_image_from_family
    if source_disk_image_override:
        init_params = {'sourceSnapshot': source_disk_image_override}
    else:
        image_response = compute.images().getFromFamily(
            project='ubuntu-os-cloud', family='ubuntu-2204-lts'
        ).execute()
        init_params = {'sourceImage': image_response['selfLink']}

    # second, initialize the parameters
    machine_type = f'zones/{zone}/machineTypes/e2-micro'
    config = {
        'name': name,
        'machineType': machine_type,

        # the boot disk, created fresh from the Ubuntu image found above.
        # autoDelete means the disk goes away when the VM does, so we don't
        # leave orphaned disks behind.
        'disks': [
            {
                'boot': True,
                'autoDelete': True,
                'initializeParams': init_params
            }
        ],

        # accessConfigs is what gives the VM a public IP address; without it
        # the VM has no external address and can't be reached from outside.
        'networkInterfaces': [
            {
                'network': 'global/networks/default',
                'accessConfigs': [
                    {'type': 'ONE_TO_ONE_NAT', 'name': 'External NAT'}
                ]
            }
        ],

        # metadata is readable from inside the instance; the 'startup-script'
        # key is special -- the guest agent fetches it and runs it at boot.
        'metadata': {
            'items': [
                {'key': 'startup-script', 'value': startup_script}
            ]
        },

        # tags set here apply at creation, so firewall rules that target
        # them (like allow-5000) take effect without a later setTags call
        'tags': {
            'items': network_tags or []
        },
    }

    # insert() returns an "operation" describing work in progress -- the VM
    # does not exist yet when this returns.
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
    """Block until a zone operation finishes.

    `operation` is the operation *name* -- the 'name' field of whatever
    insert()/delete() returned. Returns the finished operation, or raises
    if Google reported an error.
    """
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

        # poll every 0.1s so part2's creation timings are precise
        time.sleep(.1)

def firewall_rule_exists(compute, project, name):
    """True if a firewall rule called `name` already exists.

    Firewall rules are global resources, so there is no zone argument here.
    """
    result = compute.firewalls().list(project=project).execute()
    for rule in result.get('items', []):
        if rule['name'] == name:
            return True
    return False

def create_firewall_rule(compute, project, name, tag):
    """Allow TCP port 5000 from anywhere, but only to instances with `tag`."""
    config = {
        'name': name,
        'network': 'global/networks/default',

        'allowed': [
            {'IPProtocol': 'tcp', 'ports': ['5000']}
        ],

        # 0.0.0.0/0 means "from any address on the internet"
        'sourceRanges': ['0.0.0.0/0'],

        # without targetTags this rule would open port 5000 on *every* VM in
        # the network; the tag limits it to instances that opt in
        'targetTags': [tag],
    }
    return compute.firewalls().insert(project=project, body=config).execute()

def add_network_tag(compute, project, zone, instance_name, tag):
    """Put `tag` on the instance so the matching firewall rule applies to it.

    Two calls: get() to read the current tags fingerprint, then setTags() to
    write. The fingerprint proves we are modifying the version we just read --
    without it the API rejects the write.
    """
    instance = compute.instances().get(
        project=project,
        zone=zone,
        instance=instance_name
    ).execute()

    # an instance with no tags still has a fingerprint, but use .get() so a
    # missing 'tags' key can't blow up
    fingerprint = instance.get('tags', {}).get('fingerprint', '')

    # NB setTags REPLACES the tag list, it does not append to it
    return compute.instances().setTags(
        project=project,
        zone=zone,
        instance=instance_name,
        body={
            'items': [tag],
            'fingerprint': fingerprint,
        }).execute()


def get_ip(compute, project,zone, instance_name):
    instance = compute.instances().get(
        project=project,
        zone=zone,
        instance=instance_name
    ).execute()
    
    ip = instance['networkInterfaces'][0]['accessConfigs'][0]['natIP'] # from before 
    return ip 

def list_instances(compute, project, zone):
    result = compute.instances().list(project=project, zone=zone).execute()
    # return an empty list rather than None when the zone has no instances,
    # so callers can always iterate the result
    return result['items'] if 'items' in result else []

def main():
    if firewall_rule_exists(service, project, FIREWALL_RULE):
        print(f'Firewall rule {FIREWALL_RULE} already exists.')
    else:
        print(f'Creating firewall rule {FIREWALL_RULE}...')
        create_firewall_rule(service, project, FIREWALL_RULE, NETWORK_TAG)

    op = create_instance(service, project, ZONE, INSTANCE_NAME)
    wait_for_operation(service, project, ZONE, op['name'])

    # to ssh in : gcloud compute ssh troys-vm --zone=us-west1-b
    print("Your running instances are:")
    for instance in list_instances(service, project, ZONE):
        print(instance['name'])

    # GCP's firewall blocks inbound port 5000 by default. The allow-5000 rule
    # above opens it, but only for VMs carrying the allow-5000 network tag
    # (its targetTags). Without this tag flask still runs on the VM, but the
    # browser can't reach http://<ip>:5000. Here the tag is added after
    # creation with a second API call (setTags);
    print("Applying network tag...")
    tag_op = add_network_tag(service, project, ZONE, INSTANCE_NAME, NETWORK_TAG)
    wait_for_operation(service, project, ZONE, tag_op['name'])
    ip = get_ip(service, project,ZONE, INSTANCE_NAME)
    print(f"The application will be available at http://{ip}:5000 it may take several minutes to start up")

if __name__ == "__main__":
    main()
