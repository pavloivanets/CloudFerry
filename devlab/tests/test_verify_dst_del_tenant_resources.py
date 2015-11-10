import tests.config as config
import tests.functional_test as functional_test

# Create all possible openstack objects in created tenant
#
#     Neutron
#         Network
#         Subnet
#         Port
#         Router
#     Keystone
#         User
#     Glance
#         Image
#     Nova
#         VM
#         Flavor
#         Keypair
#     Cinder
#         Volume
#         Snapshot

TEST_TENANT_NAME = 'tenant3'


class VerifyDstDeletedTenantResources(functional_test.FunctionalTest):

    def setUp(self):
        self.dst_cloud.switch_user(user=self.dst_cloud.username,
                                   password=self.dst_cloud.password,
                                   tenant='admin')

        (self.tenant_res_dict,) = \
            [tenant for tenant in config.tenants
             if tenant['name'] == TEST_TENANT_NAME]

        self.tenants = {ten.name: ten.id for
                        ten in self.dst_cloud.keystoneclient.tenants.list()}

        dst_cinder_volumes = self.dst_cloud.cinderclient.volumes.list(
            search_opts={'all_tenants': 0})
        self.dst_volumes_admin = \
            {vol.display_name: vol for vol in dst_cinder_volumes}

        self.dst_vm_list = \
            self.dst_cloud.novaclient.servers.list(
                search_opts={'tenant_id': self.tenants['admin']})

        self.tenant_users_list = \
            [user for user in config.users if
             'tenant' in user and user['tenant'] == TEST_TENANT_NAME]

        user_names_tenant = [user['name'] for user in self.tenant_users_list]
        user_names_with_keypair = [key['user'] for key in config.keypairs]
        self.tenant_users_with_keyp = \
            set(user_names_with_keypair).intersection(user_names_tenant)

    def tenant_exists_on_dst(self, tenant_name):
        return bool(tenant_name in self.tenants)

    def test_tenant_exists_on_dst(self):
        if self.tenant_exists_on_dst(TEST_TENANT_NAME):
            msg = 'Tenant {0} exists on destination, but should be deleted!'
            self.fail(msg.format(TEST_TENANT_NAME))

    def tenant_users_exist_on_dst(self, users_dict_list):
        undeleted_users = []
        dst_users_list = self.dst_cloud.keystoneclient.users.list()
        for src_user_name in [user['name'] for user in users_dict_list]:
            if src_user_name in dst_users_list:
                if src_user_name in self.tenant_users_with_keyp:
                    continue
                else:
                    undeleted_users.append(src_user_name)
        return bool(len(undeleted_users) == len(users_dict_list))

    def test_tenant_users_exist_on_dst(self):
        if self.tenant_users_exist_on_dst(self.tenant_users_list):
            msg = 'Tenant\'s users {0} exist on destination,' \
                  ' but should be deleted!'
            self.fail(msg.format(self.tenant_users_list))

    def net_is_attached_to_vm(self, src_net_name):
        networks_names_lists = [vm.networks.keys() for vm in self.dst_vm_list]
        network_names_list = sum(networks_names_lists, [])
        return bool(src_net_name in network_names_list)

    def tenant_networks_exist_on_dst(self):
        dst_nets = self.dst_cloud.neutronclient.list_networks(
            all_tenants=False)['networks']
        nets_ids_list = []
        for dst_net in dst_nets:
            for src_net in self.tenant_res_dict['networks']:
                if dst_net['name'] == src_net['name']:
                    if not self.net_is_attached_to_vm(src_net['name']):
                        nets_ids_list.append(dst_net['id'])
        return bool(nets_ids_list), nets_ids_list

    def test_tenant_network_exists_on_dst(self):
        result, net_ids_list = self.tenant_networks_exist_on_dst()
        if result:
            msg = 'Tenant\'s network {0} exists on destination,' \
                  ' but should be deleted!'
            self.fail(msg.format(net_ids_list))

    def tenant_vm_exists_on_dst(self, src_vm_list):
        # according to current implementation,all tenant's vms
        # should be moved tothe 'admin' account
        src_vm_names = [vm['name'] for vm in src_vm_list]
        migrated_vm_list = []
        for dst_vm in self.dst_vm_list:
            for src_vm in src_vm_list:
                if src_vm['name'] == dst_vm.name:
                    if self.tenants['admin'] == dst_vm.tenant_id:
                        migrated_vm_list.append(dst_vm.name)
        result = bool(len(migrated_vm_list) == len(src_vm_list))
        undeleted_vms = set(src_vm_names) ^ set(migrated_vm_list)
        return result, undeleted_vms

    def test_tenant_vm_exists_on_dst(self):
        tenant_vm_list = self.tenant_res_dict['vms']
        all_vms_migrated, undeleted_vms = \
            self.tenant_vm_exists_on_dst(tenant_vm_list)
        if not all_vms_migrated:
            msg = 'Tenant\'s vm {0} does not exist on destination,' \
                  ' but should be!'
            self.fail(msg.format(undeleted_vms))

    def volume_is_attached_to_vm(self, vol_name, vol_obj):
        match_vm_id = 0
        for attached_dev in vol_obj.attachments:
            for dst_vm in self.dst_vm_list:
                if dst_vm.id == attached_dev['server_id']:
                    match_vm_id += 1
        return bool(len(vol_obj.attachments) == match_vm_id)

    def cinder_volumes_exist_on_dst(self, src_volumes_list):
        result_vol_ids = 0
        for volume_name, volume_obj in self.dst_volumes_admin.iteritems():
            if volume_name in [vol['display_name'] for
                               vol in src_volumes_list]:
                if self.volume_is_attached_to_vm(volume_name, volume_obj):
                    continue
                else:
                    result_vol_ids.append(volume_obj.id)
        return bool(result_vol_ids), result_vol_ids

    def test_tenant_cinder_volumes_on_dst(self):
        tenant_cinder_volumes_list = self.tenant_res_dict['cinder_volumes']
        undeleted_volumes, vol_ids = \
            self.cinder_volumes_exist_on_dst(tenant_cinder_volumes_list)
        if undeleted_volumes:
            msg = 'Tenant\'s cinder volumes with ids {0} exist on destination,'\
                  ' but should be deleted!'
            self.fail(msg.format(vol_ids))

    def test_tenant_key_exists_on_dst(self):
        migrated_keys = \
            [key['name'] for key in config.keypairs if
             key['user'] in self.tenant_users_with_keyp]
        keys_list = []
        for dst_vm in self.dst_vm_list:
            for src_vm in self.tenant_res_dict['vms']:
                if dst_vm.name == src_vm['name']:
                    if 'key_name' not in src_vm:
                        continue
                    if dst_vm.key_name not in migrated_keys:
                        keys_list.append(dst_vm.key_name)
        if keys_list:
            msg = 'Tenant\'s key_pairs {0} exist on destination,' \
                  ' but should be deleted!'
            self.fail(msg.format(keys_list))

    def test_tenant_flavors_exist_on_dst(self):
        dst_flavors_list = [flavor.name for flavor in
                            self.dst_cloud.novaclient.flavors.list()]
        flvlist = []
        for src_vm in self.tenant_res_dict['vms']:
            if not src_vm['flavor'] in dst_flavors_list:
                flvlist.append(src_vm['flavor'])
        if flvlist:
            msg = 'Tenant\'s flavors {0} do not exist on destination,' \
                  ' but should be!'
            self.fail(msg.format(flvlist))

    def test_subnets_exist_on_dst(self):

        all_subnets = self.dst_cloud.neutronclient.list_subnets()
        dst_admin_subnets = [subnet for subnet in
                             all_subnets['subnets'] if
                             subnet['tenant_id'] == self.tenants['admin']]

        net_list = []
        for network in self.tenant_res_dict['networks']:
            net_list.append(network['subnets'])
        src_tenant_subnets_list = sum(net_list, [])

        migrated_subnets = []
        for src_subnet in src_tenant_subnets_list:
            for dst_subnet in dst_admin_subnets:
                if src_subnet['name'] == dst_subnet['name']:
                    migrated_subnets.append(src_subnet['name'])

        src_tenant_net_names = [subnet['name'] for
                                subnet in src_tenant_subnets_list]

        non_migrated_subnets = set(
            src_tenant_net_names) ^ set(migrated_subnets)

        if non_migrated_subnets:
            msg = 'Tenant\'s subnets do not exist on destination,' \
                  ' but should be!'
            self.fail(msg.format(non_migrated_subnets))
