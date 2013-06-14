import logging
from boto import ec2


class AWSHosts:
    def __init__(self, region, filters, host_properties):
        self.logger = logging.getLogger(__name__)
        self.region = region
        self.filters = filters
        self.hosts = []

        ec2Conn = ec2.connect_to_region(self.region)
        self.reservations = ec2Conn.get_all_instances(filters=filters)
        self.instances = [inst for res in self.reservations for inst in res.instances]

        for inst in self.instances:
            myhost = {}
            myhost['host_name'] = self.build_nagios_field(inst, 'host_name', host_properties['host_name'])
            myhost['alias'] = self.build_nagios_field(inst, 'alias', host_properties['alias'])
            myhost['address'] = self.build_nagios_field(inst, 'address', host_properties['address'])
            myhost['type'] = self.build_nagios_field(inst, 'type', host_properties['type'])

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
