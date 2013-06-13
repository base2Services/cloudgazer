from boto import ec2


class AWSHosts:
    def __init__(self, region, filters, host_properties):
        self.region = region
        self.filters = filters
        self.hosts = []

        ec2Conn = ec2.connect_to_region(self.region)
        self.reservations = ec2Conn.get_all_instances(filters=filters)
        self.instances = [inst for res in self.reservations for inst in res.instances]

        for inst in self.instances:
            myhost = {}
            #build host_name
            hostNameParts = []
            for prop in host_properties['host_name']:
                if prop.startswith('tag:'):
                    tag = prop.split(':')[1]
                    hostNameParts.append(str(inst.tags[tag]))
                else:
                    hostNameParts.append(str(getattr(inst, prop)))
            myhost['host_name'] = '-'.join(hostNameParts)
            self.hosts.append(myhost)
