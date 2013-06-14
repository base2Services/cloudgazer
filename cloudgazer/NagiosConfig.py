import logging
import os.path
import sqlite3


class NagiosConfig:
    def __init__(self, configPath, databaseFile):
        self.logger = logging.getLogger(__name__)
        self.configPath = configPath
        self.databaseFile = databaseFile

        if not os.path.exists(self.configPath):
            self.logger.critical('Nagios configuration path does not exist, exiting.')
            exit(1)
        if not os.path.exists(self.databaseFile):
            self.logger.warning('SQLite database does not exist, creating new one.')

        #Connect to sqlite database and create nagios_hosts table if it doesn't exist
        try:
            self.dbconn = sqlite3.connect(databaseFile)
            self.cur = self.dbconn.cursor()
            self.cur.execute('SELECT name FROM sqlite_master WHERE type=\'table\' AND name=\'nagios_hosts\';')
            if len(self.cur.fetchall()) < 1:
                self.logger.debug('No table called nagios_hosts found. Creating...')
                self.cur.execute('CREATE TABLE nagios_hosts(host_name TEXT, alias TEXT, address TEXT, PRIMARY KEY (host_name));')
        except sqlite3.Error as e:
            self.logger.critical("Something bad happened trying to use the SQLite database, error: %s" % e.args[0])
            self.dbconn.close()
            exit(1)

    def updateDB(self, hosts):
        """
        Takes a dict of nagios hosts, compares them to the database and updates as required
        """
        changeList = {}
        currentHosts = self.getSQLHosts()
        newHosts = hosts
        todbHosts = []
        currentHosts2 = currentHosts[:]

        for nhost in newHosts:
            exists = False
            for chost in currentHosts:
                if nhost['host_name'] == chost['host_name']:
                    currentHosts2.remove(chost)
                    exists = True
                    different = []
                    #nhost already exists in database
                    if not nhost['alias'] == chost['alias']:
                        different.append('alias')
                    if not nhost['address'] == chost['address']:
                        different.append('address')
                    if len(different) > 0:
                        changeList[chost['host_name']] = "updated:%s" % (':'.join(different))
                    todbHosts.append(nhost)
            if not exists:
                #nhost doesnt exist in currentHosts
                todbHosts.append(nhost)
                changeList[nhost['host_name']] = 'added'
        if len(currentHosts2) > 0:
            for host in currentHosts2:
                changeList[host['host_name']] = 'removed'

        self.logger.debug("Change list: %s" % (changeList))

    def getSQLHosts(self):
        hosts = []
        for row in self.dbconn.execute('SELECT host_name, alias, address FROM nagios_hosts;'):
            (hostName, alias, address) = row
            hosts.append({'host_name': str(hostName), 'alias': str(alias), 'address': str(address)})
        return hosts
        
