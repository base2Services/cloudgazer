#!/usr/bin/env python
# Peter Hall 13/06/2013
#
# Cloudgazer: Looks at your instances in EC2 and generates nagios config for them

import argparse
import logging
import os.path
import yaml
from AWSHosts import AWSHosts
from NagiosConfig import NagiosConfig


def main():
    #parse command line options
    argParse = argparse.ArgumentParser()
    argParse.add_argument('-c', '--config_file', dest='configFile', default='~/.cloudgazer.yaml', help='Cloudgazer configuration file location. Defaults to ~/.cloudgazer')
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
    conf_fo = open(configFile, 'r')
    config = yaml.safe_load(conf_fo)
    conf_fo.close()
    
    #get ec2 region
    region = config['ec2']['region']

    #get paths for nagios config
    nagiosDir = os.path.expanduser(config['nagios']['host_dir'])
    
    #get database config
    if config['database']['type'] != 'sqlite':
        logger.critical('Database type: %s, not currently supported. Only sqlite for now')
        exit(1)
    sqliteDbFile = os.path.expanduser(config['database']['location'])

    #Grab the bits of the config we need to give to AWSHosts class
    templateMap = config['template_map']
    mappings = config['mappings']
    filters = config['ec2']['filters']

    awsHosts = AWSHosts(region=region, filters=filters, mappings=mappings, templateMap=templateMap)
    
    #print len(awsHosts.instances)
    for host in awsHosts.hosts:
        for map in config['mappings']:
            logger.debug("Host: %s, Nagios field: %s, Value: %s" % (host["host_name"], config['mappings'][map]['nagios_field'], host[config['mappings'][map]['nagios_field']]))

    nagiosConf = NagiosConfig(configPath=nagiosDir, databaseFile=sqliteDbFile)
    changedHosts = nagiosConf.updateDB(awsHosts.hosts)
    logger.info(nagiosConf.configPath)

if __name__ == '__main__':
    main()
