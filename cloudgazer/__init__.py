#!/usr/bin/env python
# Peter Hall 13/06/2013
#
# Cloudgazer: Looks at your instances in EC2 and generates nagios config for them

import argparse
import logging
import os.path
import yaml
from AWSHosts import AWSHosts
from Nagios import Config as NagiosConfig
from Nagios import Writer as NagiosWriter


def main():
    #parse command line options
    argParse = argparse.ArgumentParser()
    argParse.add_argument('-c', '--config_file', dest='configFile', default='~/.cloudgazer.yaml', help='Cloudgazer configuration file location. Defaults to ~/.cloudgazer.yaml')
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
    hostIdent = config['nagios']['host_identifier']
    nagiosFields = [config['mappings'][map]['nagios_field'] for map in config['mappings']]
    nagiosSplitBy = config['nagios']['separate_hosts_by']
    if nagiosSplitBy not in nagiosFields and nagiosSplitBy.lower() != 'none':
        logger.critical('separate_hosts_by not set to a known nagios host field')
        exit(1)

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

    nagiosConf = NagiosConfig(configPath=nagiosDir, databaseFile=sqliteDbFile, hostIdent=hostIdent, nagiosFields=nagiosFields)
    changedHosts = nagiosConf.updateDB(awsHosts.hosts)

    if len(changedHosts) > 0:
        logger.debug('Host list changed, writing nagios config')
        NagiosWriter(configDir=nagiosDir, hosts=awsHosts.hosts, changedHosts=changedHosts, splitBy=nagiosSplitBy)
        Notify('SNS', changedHosts)
    else:
        logger.debug('No change to host list. Nothing to do.')


class Notify:
    def __init__(self, method, changedHosts):
        self.message = ''
        self.changedHosts = changedHosts

        print self._generate_message(changedHosts)

    def _generate_message(self, changedHosts):
        message = 'AWS Hosts in nagios have changed:\n\n'
        hostsAdded = []
        hostsUpdated = []
        hostsRemoved = []

        for host in changedHosts:
            if changedHosts[host] == 'added':
                hostsAdded.append(host)
            elif changedHosts[host] == 'removed':
                hostsRemoved.append(host)
            elif changedHosts[host].startswith('updated'):
                fields = []
                for field in changedHosts[host].split(':'):
                    if field == 'updated':
                        continue
                    fields.append(field)
                hostsUpdated.append("%s (%s)" % (host, ', '.join(fields)))
        message += "- New hosts (%s): %s\n" % (len(hostsAdded), ", ".join(hostsAdded))
        message += "- Removed hosts (%s): %s\n" % (len(hostsRemoved), ", ".join(hostsRemoved))
        message += "- Updated hosts (%s): %s\n" % (len(hostsUpdated), ", ".join(hostsUpdated))

        return message

if __name__ == '__main__':
    main()
