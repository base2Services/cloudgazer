import logging
import os.path
import sqlite3


class NagiosConfig:
    def __init__(self, configPath, databaseFile, hostIdent, nagiosFields):
        self.logger = logging.getLogger(__name__)
        self.configPath = configPath
        self.databaseFile = databaseFile
        self.hostIdent = hostIdent
        self.nagiosFields = nagiosFields

        #Build create table statement
        nagiosFieldsStr = ' TEXT, '.join(self.nagiosFields)
        createTable = "CREATE TABLE nagios_hosts(%s TEXT, PRIMARY KEY (%s))" % (nagiosFieldsStr, self.hostIdent)

        if not os.path.exists(self.configPath):
            self.logger.critical('Nagios configuration path does not exist, exiting.')
            exit(1)
        if not os.path.exists(self.databaseFile):
            self.logger.warning('SQLite database does not exist, creating new one.')

        #Connect to sqlite database and create nagios_hosts table if it doesn't exist
        try:
            self.dbconn = sqlite3.connect(databaseFile)
            self.cur = self.dbconn.cursor()
            #check this database was created with the same host fields as we have now, otherwise it needs to be deleted
            self.cur.execute('SELECT sql FROM sqlite_master WHERE type=\'table\' AND name = \'nagios_hosts\';')
            row = self.cur.fetchone()
            #self.cur.execute('SELECT name FROM sqlite_master WHERE type=\'table\' AND name=\'nagios_hosts\';')
            if not row:
                self.logger.debug('No table called nagios_hosts found. Creating...')
                self.cur.execute(createTable)
            else:
                extraField = False
                cols = str(row[0][row[0].find('('):].strip('()')).split(',')
                checkFields = nagiosFields[:]
                for col in cols:
                    if col.strip().startswith('PRIMARY'):
                        continue
                    fieldName = col.strip().split(' ')[0]
                    if not fieldName in checkFields:
                        extraField = True
                        break
                    checkFields.remove(fieldName)
                if len(checkFields) > 0 or extraField:
                    #nagios fields have changed since database creation
                    self.logger.critical('Fields in database do not match yaml file. Delete database if you are sure yaml is correct')
                    self.logger.critical("Current database table create statement: %s" % (row[0]))
                    self.logger.critical("New database table create statement: %s" % (createTable))
                    exit(1)

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
        currentHosts2 = currentHosts[:]

        for nhost in hosts:
            exists = False
            for chost in currentHosts:
                if nhost[self.hostIdent] == chost[self.hostIdent]:
                    currentHosts2.remove(chost)
                    exists = True
                    different = []
                    #nhost already exists in database
                    for attrib in nhost:
                        if attrib == self.hostIdent:
                            continue
                        if not nhost[attrib] == chost[attrib]:
                            different.append(attrib)
                    if len(different) > 0:
                        self.updateHostinDB(nhost)
                        changeList[chost[self.hostIdent]] = "updated:%s" % (':'.join(different))
            if not exists:
                #nhost doesnt exist in currentHosts
                self.addHosttoDB(nhost)
                changeList[nhost[self.hostIdent]] = 'added'
        if len(currentHosts2) > 0:
            for host in currentHosts2:
                self.deleteHostinDB(host)
                changeList[host[self.hostIdent]] = 'removed'

        self.logger.debug("Change list: %s" % (changeList))
        return changeList

    def getSQLHosts(self):
        hosts = []
        selectStr = "SELECT %s FROM nagios_hosts;" % (','.join(self.nagiosFields))
        for row in self.dbconn.execute(selectStr):
            hostHash = {}
            for x in range(0, len(self.nagiosFields)):
                hostHash[self.nagiosFields[x]] = str(row[x])
            hosts.append(hostHash)
        return hosts

    def addHosttoDB(self, host):
        cols = []
        values = []
        for field in host:
            cols.append(field)
            values.append('"' + host[field] + '"')
        insertSQL = "INSERT INTO nagios_hosts(%s) VALUES(%s);" % (', '.join(cols), ', '.join(values))
        self.logger.debug("Adding a host to DB: %s" % insertSQL)
        self.dbconn.execute(insertSQL)
        self.dbconn.commit()

    def updateHostinDB(self, host):
        values = []
        for field in host:
            values.append(field + '="' + host[field] + '"')

        updateSQL = "UPDATE nagios_hosts SET %s WHERE %s;" % (', '.join(values), self.hostIdent + '="' + host[self.hostIdent] + '"')
        self.logger.debug("Updating a host in DB: %s" % updateSQL)
        self.dbconn.execute(updateSQL)
        self.dbconn.commit()

    def deleteHostinDB(self, host):
        deleteSQL = "DELETE FROM nagios_hosts WHERE %s;" % (self.hostIdent + '="' + host[self.hostIdent] + '"')
        self.logger.debug("Deleting a host from DB: %s" % deleteSQL)
        self.dbconn.execute(deleteSQL)
        self.dbconn.commit()
