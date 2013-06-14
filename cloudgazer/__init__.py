#!/usr/bin/env python
# Peter Hall 13/06/2013
#
# Cloudgazer: Looks at your instances in EC2 and generates nagios config for them

import argparse
import logging
import os.path
from AWSHosts import AWSHosts
from configobj import ConfigObj
from NagiosConfig import NagiosConfig


def main():
    #parse command line options
    argParse = argparse.ArgumentParser()
    argParse.add_argument('-c', '--config_file', dest='configFile', default='~/.cloudgazer', help='Cloudgazer configuration file location. Defaults to ~/.cloudgazer')
    argParse.add_argument('-l', '--log', dest='loglevel', required=False, default="info", help="Log Level for output messages, CRITICAL, ERROR, WARNING, INFO or DEBUG")
    args = argParse.parse_args()

    #set up logging
    numeric_level = getattr(logging, args.loglevel.upper(), None)
    if not isinstance(numeric_level, int):
        print 'Invalid log level: %s' % args.loglevel
        exit(1)
    logging.basicConfig(level=numeric_level)
    logger = logging.getLogger(__name__)

    #Parse configuration file
    configFile = os.path.expanduser(args.configFile)
    if not os.path.exists(configFile):
        print "Error: Configuration file %s doesn't exist." % (args.configFile)
        exit(1)
    config = ConfigObj(configFile)

    #get ec2 region
    region = config['ec2_region']

    #get paths for nagios config and sqlite db
    nagiosDir = os.path.expanduser(config['nagios_conf_dir'])
    sqliteDbFile = os.path.expanduser(config['sqlite_database'])

    #get mapping of aws to nagios host fields
    host_properties = {'address': config['address_property']}
    host_properties['host_name'] = config['hostname_properties']
    host_properties['alias'] = config['alias_properties']
    host_properties['type'] = config['host_type']
    host_properties['template_map'] = dict(config['template map'])

    #Convert filters in config file into a dict
    filters = dict(config['filters'])

    awsHosts = AWSHosts(region=region, filters=filters, host_properties=host_properties)
    #print len(awsHosts.instances)
    for host in awsHosts.hosts:
        logger.debug("Hostname: %s" % (host["host_name"]))
        logger.debug("Alias: %s" % (host["alias"]))
        logger.debug("Address: %s" % (host["address"]))
        logger.debug("Use: %s" % (host["type"]))

    nagiosConf = NagiosConfig(configPath=nagiosDir, databaseFile=sqliteDbFile)
    changedHosts = nagiosConf.updateDB(awsHosts.hosts)
    logger.info(nagiosConf.configPath)

if __name__ == '__main__':
    main()
