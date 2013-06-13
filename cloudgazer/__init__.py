#!/usr/bin/env python
# Peter Hall 13/06/2013
#
# Cloudgazer: Looks at your instances in EC2 and generates nagios config for them

import argparse
import logging
import os.path
from AWSHosts import AWSHosts
from configobj import ConfigObj


def main():
    configFileDefault = "%s/.cloudgazer" % (os.path.expanduser('~'))
    argParse = argparse.ArgumentParser()
    argParse.add_argument('-c', '--config_file', dest='configFile', default=configFileDefault, help="Cloudgazer configuration file location. Defaults to %s" % (configFileDefault))
    args = argParse.parse_args()

    #Parse configuration file
    if not os.path.exists(args.configFile):
        print "Error: Configuration file %s doesn't exist." % (args.configFile)
        exit(1)
    config = ConfigObj(args.configFile)

    #get ec2 region
    region = config['ec2_region']

    #get mapping of aws to nagios host fields
    host_properties = {'address': config['address_property']}
    host_properties['host_name'] = config['hostname_properties']
    host_properties['alias'] = config['alias_properties']
    host_properties['type_tag'] = config['host_type_tag']
    host_properties['template_map'] = dict(config['template map'])

    #Convert filters in config file into a dict
    filters = dict(config['filters'])

    awsHosts = AWSHosts(region=region, filters=filters, host_properties=host_properties)
    #print len(awsHosts.instances)
    for host in awsHosts.hosts:
        print host["host_name"]




if __name__ == '__main__':
    main()
