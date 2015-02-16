import logging
import os.path
import sqlite3
import shlex
from subprocess import check_call, check_output, CalledProcessError
import time
import datetime
import pwd


class Config:
    def __init__(self, configPath, databaseFile, hostIdent, nagiosFields):
        self.logger = logging.getLogger(__name__)
        self.configPath = configPath
        self.databaseFile = databaseFile
        self.hostIdent = hostIdent
        self.nagiosFields = nagiosFields

        # Build create table statement
        nagiosFieldsStr = ' TEXT, '.join(self.nagiosFields)
        createTable = "CREATE TABLE nagios_hosts(%s TEXT, PRIMARY KEY (%s))" % (nagiosFieldsStr, self.hostIdent)

        if not os.path.exists(self.databaseFile):
            self.logger.warning('SQLite database does not exist, creating new one.')

        # Connect to sqlite database and create nagios_hosts table if it doesn't exist
        try:
            self.dbconn = sqlite3.connect(databaseFile)
            self.cur = self.dbconn.cursor()
            # check this database was created with the same host fields as we have now, otherwise it needs to be deleted
            self.cur.execute('SELECT sql FROM sqlite_master WHERE type=\'table\' AND name = \'nagios_hosts\';')
            row = self.cur.fetchone()
            # self.cur.execute('SELECT name FROM sqlite_master WHERE type=\'table\' AND name=\'nagios_hosts\';')
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
                    if fieldName not in checkFields:
                        extraField = True
                        break
                    checkFields.remove(fieldName)
                if len(checkFields) > 0 or extraField:
                    # nagios fields have changed since database creation
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
                    # nhost already exists in database
                    for attrib in nhost:
                        if attrib == self.hostIdent:
                            continue
                        if not nhost[attrib] == chost[attrib]:
                            different.append(attrib)
                    if len(different) > 0:
                        self.updateHostinDB(nhost)
                        changeList[chost[self.hostIdent]] = "updated:%s" % (':'.join(different))
            if not exists:
                # nhost doesnt exist in currentHosts
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


class Writer:
    def __init__(self, configDir, hosts, changedHosts, splitBy):
        self.logger = logging.getLogger(__name__)
        self.configDir = configDir
        if not os.path.isdir(self.configDir):
            self.logger.critical('Nagios configuration path does not exist, exiting.')
            exit(1)

        # remove all the files in the directory currently
        filelist = [f for f in os.listdir(self.configDir) if f.endswith(".cfg")]
        for f in filelist:
            os.remove(self.configDir + '/' + f)

        if splitBy.lower() == 'none':
            newFiles = ['cloudgazer.cfg']
        else:
            newFiles = {}
            for host in hosts:
                filename = "cloudgazer_%s.cfg" % (host[splitBy])
                if filename not in newFiles:
                    newFiles[filename] = self._convertHostToStr(host)
                else:
                    newFiles[filename] += self._convertHostToStr(host)
        self.logger.debug("new files: %s" % (newFiles))

        for file in newFiles:
            new_host_cfg_path = os.path.join(self.configDir, file)
            with open(new_host_cfg_path, 'w') as f:
                f.write(newFiles[file])
                # Check to see if we have a file called foo.cfg.services.
                # if so, nclude it in our host file generation to get around
                # an issue we're seeing with empty ASGs causing Nagios Config
                # errors due to services being defined for hosts that don't
                # exist anymore.
                if os.path.isfile(new_host_cfg_path + '.services'):
                    with open(new_host_cfg_path + '.services') as svc_file:
                        for l in svc_file:
                            f.write(l)

    def _convertHostToStr(self, host):
        hostStr = 'define host {\n'
        longestField = 0
        for field in host:
            if len(field) > longestField:
                longestField = len(field)
        for field in host:
            tabStr = '' + '\t' * ((longestField / 4) - (len(field) / 4))
            hostStr += "\t%s\t\t%s%s\n" % (field, tabStr, host[field])
        hostStr += '}\n\n'
        return hostStr

    def _getFileName(self, host, splitBy):
        if splitBy.lower() == 'none':
            return 'cloudgazer.cfg'
        else:
            return "cloudgazer_%s.cfg" % (host[splitBy])


class Manager:
    """
    Looks after verifying config and restarting Nagios
    """
    def __init__(self, config):
        self.logger = logging.getLogger(__name__)
        self.config = config

    def verifyConfig(self):
        status = {}
        try:
            self.logger.debug("Verifying nagios config, running: %s" % (self.config['test_config_cmd']))
            status['output'] = check_output(shlex.split(self.config['test_config_cmd']))
            status['ok'] = True
            return status
        except OSError as e:
            self.logger.debug("Nagios verify failed to execute: %s" % (e.strerror))
            status['ok'] = False
            status['output'] = e.strerror
            return status
        except CalledProcessError as e:
            self.logger.debug("Nagios verify failed. Return code: %s" % (e.returncode))
            status['ok'] = False
            status['output'] = e.output
            return status

    def restart(self):
        try:
            self.logger.debug("Restarting nagios with command: %s" % (self.config['restart_cmd']))
            check_call(shlex.split(self.config['restart_cmd']))
            return True
        except OSError as e:
            self.logger.debug("Nagios restart failed to execute: %s" % (e.strerror))
            return False
        except CalledProcessError as e:
            self.logger.debug("Nagios restart failed. Return code: %s" % (e.returncode))
            return False


class Downtime:
    """
    Looks after scheduling downtime in Nagios
    The shell version is
    now=`date +%s`
    printf "[%lu] SCHEDULE_HOST_SVC_DOWNTIME;homeapi@absinthe-home-api-i-4e75a770
   ;${now};$((${now} + 900 ));0;0;1800;nagios;Testing cloudgazer\n" "${now}" >$commandfile

    SCHEDULE_HOST_SVC_DOWNTIME;<host_name>;<start_time>;<end_time>;<fixed>;<trigger_id>;<duration>;<author>;<comment>

    Schedules downtime for all services associated with a particular host.
    If the "fixed" argument is set to one (1), downtime will start and end at
    the times specified by the "start" and "end" arguments.

    """
    def __init__(self, changedHosts, icingaCmdFile):
        self.logger = logging.getLogger(__name__)
        self.icingaCmdFile = icingaCmdFile
        self.changedHosts = changedHosts
        # F U Python and your random fail os.path permissions weirdness
#         if not os.path.exists(self.icingaCmdFile):
#            self.logger.critical("icinga cmdfile: %s does not exist, exiting." % (self.icingaCmdFile))
#            exit(1)
        dt = datetime.datetime.now()
        dtStart_time = time.mktime(dt.timetuple())
        end = dt + datetime.timedelta(minutes=10)
        dtEnd_time = time.mktime(end.timetuple())

        dtCommand = "SCHEDULE_HOST_SVC_DOWNTIME"
        dtComment = "Cloudgazer downtime to allow host to initialise"
        dtAuthor = "nagios"
        # Duration in seconds
        dtDuration = 900
        runas = pwd.getpwnam('nagios')
        self.logger.debug("current euid %s , uid %s " % (os.geteuid(), os.getuid()))
        self.logger.debug("Waiting for 10 seconds for icinga to come backup")
        time.sleep(10)
        for hosts in changedHosts:

            os.seteuid(runas.pw_uid)
            if changedHosts[hosts] == 'added':
                dtHost_name = hosts
                dtMessage = "[%d] %s;%s;%d;%d;0;0;%d;%s;%s; \n " % (dtStart_time,
                                                                    dtCommand,
                                                                    dtHost_name,
                                                                    dtStart_time,
                                                                    dtEnd_time,
                                                                    dtDuration,
                                                                    dtAuthor,
                                                                    dtComment)
                try:
                    self.logger.debug("current euid %s , uid %s " % (os.geteuid(),
                                                                     os.getuid()))
                    f = open(icingaCmdFile, 'w')
                    self.logger.debug("message to icinga: %s " % (dtMessage))
                    f.write(dtMessage)
                except IOError:
                    self.logger.debug("Cannot open icinga cmdfile: %s " % (self.icingaCmdFile))
                f.close()
            os.seteuid(0)

        self.logger.debug("current euid %s , uid %s " % (os.geteuid(), os.getuid()))
