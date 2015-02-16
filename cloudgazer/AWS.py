import logging
from boto import ec2
from boto import sns


class Hosts:
    def __init__(self, region, filters, mappings, templateMap, exclude_tag):
        self.logger = logging.getLogger(__name__)
        self.region = region
        self.filters = filters
        self.exclude_tag = exclude_tag
        self.hosts = []

        ec2Conn = ec2.connect_to_region(self.region)
        self.reservations = ec2Conn.get_all_instances(filters=filters)
        self.instances = [inst for res in self.reservations
                          for inst in res.instances
                          if self.exclude_tag not in inst.tags]

        for inst in self.instances:
            myhost = {}
            for map in mappings:
                myhost[mappings[map]['nagios_field']] = self.build_nagios_field(inst,
                                                                                mappings[map]['nagios_field'],
                                                                                mappings[map]['ec2_instance_property'])
            self.hosts.append(myhost)

    def build_nagios_field(self, instance, fieldName, fieldProperties):
        """
        Takes an ec2 instance object, field properties (to map the nagios field to instance attribute(s) ) and a nagios field name.
        Returns the field name for the provided instance object
        """
        if type(fieldProperties) is list:
            fieldParts = []
            for prop in fieldProperties:
                if prop.startswith('tag:'):
                    tag = prop.split(':')[1]
                    fieldParts.append(str(instance.tags[tag]))
                else:
                    try:
                        fieldParts.append(str(getattr(instance, prop)))
                    except AttributeError:
                        self.logger.critical("Unable to find instance attribute %s when building nagios field %s" % (prop, fieldName))
                        exit(1)
                    return '-'.join(fieldParts)
        elif type(fieldProperties) is str:
            if fieldProperties.startswith('tag:'):
                tag = fieldProperties.split(':')[1]
                return str(instance.tags[tag])
            else:
                try:
                    return str(getattr(instance, fieldProperties))
                except AttributeError:
                    self.logger.critical("Unable to find instance attribute %s when building nagios field %s" % (fieldProperties, fieldName))
                    exit(1)


class SNSNotify:
    def __init__(self, region, topic):
        self.region = region
        self.topic = topic
        self._snsConn = sns.connect_to_region(region)

    def publish(self, message, subject):
        return self._snsConn.publish(self.topic, message, subject)
