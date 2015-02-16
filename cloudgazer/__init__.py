#!/usr/bin/env python
# Peter Hall 13/06/2013
#
# Cloudgazer: Discovers EC2 instances and generates nagios config for them

import argparse
import logging
import os.path
import socket
import yaml
from AWS import Hosts as AWSHosts
from AWS import SNSNotify
from Nagios import Config as NagiosConfig
from Nagios import Writer as NagiosWriter
from Nagios import Manager as NagiosManager
from Nagios import Downtime as NagiosDowntime


def main():
    # parse command line options
    argParse = argparse.ArgumentParser()
    argParse.add_argument('-c', '--config_file',
                          dest='configFile',
                          default='~/.cloudgazer.yaml',
                          help='Cloudgazer configuration file location.'
                               ' Defaults to ~/.cloudgazer.yaml')
    argParse.add_argument('-l', '--log',
                          dest='loglevel',
                          required=False,
                          default="info",
                          help='Log Level for output messages,'
                               ' CRITICAL, ERROR, WARNING, INFO or DEBUG')
    args = argParse.parse_args()

    # set up logging
    numeric_level = getattr(logging, args.loglevel.upper(), None)
    if not isinstance(numeric_level, int):
        print 'Invalid log level: %s' % args.loglevel
        exit(1)
    logging.basicConfig(level=numeric_level)
    logger = logging.getLogger(__name__)

    # Parse configuration file
    configFile = os.path.expanduser(args.configFile)
    if not os.path.exists(configFile):
        print "Error: Configuration file %s doesn't exist." % (args.configFile)
        exit(1)
    conf_fo = open(configFile, 'r')
    config = yaml.safe_load(conf_fo)
    conf_fo.close()

    # get ec2 region
    region = config['ec2']['region']

    # get paths for nagios config
    nagiosDir = os.path.expanduser(config['nagios']['host_dir'])
    hostIdent = config['nagios']['host_identifier']
    nagiosFields = [config['mappings'][map]['nagios_field'] for map in config['mappings']]
    nagiosSplitBy = config['nagios']['separate_hosts_by']
    icingaCmdFile = config['nagios']['command_file']
    if nagiosSplitBy not in nagiosFields and nagiosSplitBy.lower() != 'none':
        logger.critical('separate_hosts_by not set to a known nagios host field')
        exit(1)

    # get database config
    if config['database']['type'] != 'sqlite':
        logger.critical('Database type: %s, not currently supported. Only sqlite for now')
        exit(1)
    sqliteDbFile = os.path.expanduser(config['database']['location'])

    # Grab the bits of the config we need to give to AWSHosts class
    templateMap = config['template_map']
    mappings = config['mappings']
    filters = config['ec2']['filters']
    if 'exclude_tag' in config['ec2']:
        exclude_tag = config['ec2']['exclude_tag']
    else:
        exclude_tag = ''

    # Notification config
    notification_conf = config['notifications']

    awsHosts = AWSHosts(region=region,
                        filters=filters,
                        mappings=mappings,
                        templateMap=templateMap,
                        exclude_tag=exclude_tag)

#    print len(awsHosts.instances)
    for host in awsHosts.hosts:
        for map in config['mappings']:
            logger.debug("Host: %s, Nagios field: %s, Value: %s" % (host["host_name"],
                                                                    config['mappings'][map]['nagios_field'],
                                                                    host[config['mappings'][map]['nagios_field']]))

    nagiosConf = NagiosConfig(configPath=nagiosDir,
                              databaseFile=sqliteDbFile,
                              hostIdent=hostIdent,
                              nagiosFields=nagiosFields)
    changedHosts = nagiosConf.updateDB(awsHosts.hosts)

    if len(changedHosts) > 0:
        logger.debug('Host list changed, writing nagios config')
        NagiosWriter(configDir=nagiosDir,
                     hosts=awsHosts.hosts,
                     changedHosts=changedHosts,
                     splitBy=nagiosSplitBy)
        Notify(method='SNS',
               changedHosts=changedHosts,
               config=notification_conf)
        nagManager = NagiosManager(config=config['nagios'])
        nag_config_check = nagManager.verifyConfig()
        if nag_config_check['ok']:
            if nagManager.restart():
                logger.debug('Nagios successfully restarted')
                if changedHosts:
                    NagiosDowntime(changedHosts, icingaCmdFile)
                    logger.debug('Scheduled downtime for hosts')
            else:
                msg = 'Failed to restart nagios'
                logger.critical(msg)
                Notify(method='SNS',
                       config=notification_conf,
                       type='error',
                       message=msg,
                       subject='Cloudgazer ERROR')

        else:
            msg = 'Failed to verify nagios config'
            logger.critical(msg)
            msg = msg + "\n" + nag_config_check['output']
            Notify(method='SNS',
                   config=notification_conf,
                   type='error',
                   message=msg,
                   subject='Cloudgazer ERROR')
    else:
        logger.debug('No change to host list. Nothing to do.')


class Notify:
    def __init__(self, config, method, type='host_change', message=None,
                 changedHosts=None, subject='Cloudgazer Notification'):
        self.logger = logging.getLogger(__name__)
        self.changedHosts = changedHosts
        self.config = config
        self.hostname = socket.gethostname()
        if 'enabled' in config:
            self.notifications_enabled = config['enabled']
        else:
            self.notifications_enabled = True

        # if its a host change notification,
        # generate the message from changeHosts dict
        if type == 'host_change':
            self.message = self._generate_host_change_message(changedHosts)
        # only other type we have at the moment is an error
        # so if not host_change, assume its an error
        else:
            self.message = "On host: %s \n" % (self.hostname)
            if message:
                self.message += 'Cloudgazer encounted the following error:\n\n'
                self.message += message
            else:
                self.message += 'Cloudgazer encounted an unknown error,' \
                                ' please investigate.\n\n'

        # Send notifications unless the config specifically
        # disables it, otherwise just log
        if self.notifications_enabled:
            if method == 'SNS':
                sns = SNSNotify(region=config['sns']['region'],
                                topic=config['sns']['topic'])
                sns.publish(message=self.message, subject=subject)
        else:
            self.logger.debug('Notifications are disabled.'
                              "We Would've sent this: %s" % self.message)

    def _generate_host_change_message(self, changedHosts):
        message = "AWS Hosts in nagios have changed on %s:\n\n" % (self.hostname)
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
        message += "- New hosts (%s): \n%s\n\n" % (len(hostsAdded), "\n ".join(sorted(hostsAdded)))
        message += "- Removed hosts (%s): \n%s\n\n" % (len(hostsRemoved), "\n ".join(sorted(hostsRemoved)))
        message += "- Updated hosts (%s): \n%s\n\n" % (len(hostsUpdated), "\n ".join(sorted(hostsUpdated)))

        return message

if __name__ == '__main__':
    main()
