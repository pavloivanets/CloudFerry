"""
Package with OpenStack resources export/import utilities.
"""
import osCommon
from utils import log_step, get_log
import sqlalchemy

LOG = get_log(__name__)


class ResourceExporter(osCommon.osCommon):
    """
    Exports various cloud resources (tenants, users, flavors, etc.) to a container
    to be later imported by ResourceImporter
    """

    def __init__(self, conf):
        self.data = dict()
        super(ResourceExporter, self).__init__(conf['clouds']['from'])

    @log_step(2, LOG)
    def get_flavors(self):
        self.data['flavors'] = self.nova_client.flavors.list(is_public=None)
        return self

    @log_step(2, LOG)
    def get_tenants(self):
        self.data['tenants'] = self.keystone_client.tenants.list()
        return self

    @log_step(2, LOG)
    def get_roles(self):
        self.data['roles'] = self.keystone_client.roles.list()
        return self

    @log_step(2, LOG)
    def get_user_info(self):
        users = self.keystone_client.users.list()
        info = {}
        with sqlalchemy.create_engine(self.keystone_db_conn_url).begin() as connection:
            for user in users:
                for password in connection.execute(sqlalchemy.text("SELECT password FROM user WHERE id = :user_id"),
                                                   user_id=user.id):
                    info[user.name] = password[0]
        self.data['users'] = info
        return self

    @log_step(2, LOG)
    def build(self):
        return self.data


class ResourceImporter(osCommon.osCommon):
    """
    Imports various cloud resources (tenants, users, flavors, etc.) from a container
    prepared by ResourceExporter
    """

    def __init__(self, conf):
        super(ResourceImporter, self).__init__(conf['clouds']['to'])

    @log_step(2, LOG)
    def upload(self, data):
        self.__upload_roles(data['roles'])
        self.__upload_tenants(data['tenants'])
        self.__upload_user_passwords(data['users'])
        self.__upload_flavors(data['flavors'])

    @log_step(3, LOG)
    def __upload_roles(self, roles):
        # do not import a role if one with the same name already exists
        existing = {r.name for r in self.keystone_client.roles.list()}
        for role in roles:
            if role.name not in existing:
                self.keystone_client.roles.create(role.name)

    @log_step(3, LOG)
    def __upload_tenants(self, tenants):
        # do not import tenants or users if ones with the same name already exist
        existing_tenants = {t.name: t for t in self.keystone_client.tenants.list()}
        existing_users = {u.name: u for u in self.keystone_client.users.list()}
        # by this time roles on source and destination should be synchronized
        roles = {r.name: r for r in self.keystone_client.roles.list()}
        for tenant in tenants:
            if tenant.name not in existing_tenants:
                dest_tenant = self.keystone_client.tenants.create(tenant_name=tenant.name,
                                                                  description=tenant.description,
                                                                  enabled=tenant.enabled)
            else:
                dest_tenant = existing_tenants[tenant.name]
            # import users of this tenant that don't exist yet
            for user in tenant.list_users():
                if user.name not in existing_users:
                    dest_user = self.keystone_client.users.create(name=user.name,
                                                                  password='changeme',
                                                                  email=user.email,
                                                                  tenant_id=dest_tenant.id,
                                                                  enabled=user.enabled)
                else:
                    dest_user = existing_users[user.name]
                # import roles of this user within the tenant that are not already assigned
                dest_user_roles = {r.name for r in dest_user.list_roles(dest_tenant)}
                for role in user.list_roles(tenant):
                    if role.name not in dest_user_roles:
                        dest_tenant.add_user(dest_user, roles[role.name])

    @log_step(3, LOG)
    def __upload_flavors(self, flavors):
        # do not import a flavor if one with the same name already exists
        existing = {f.name for f in self.nova_client.flavors.list(is_public=None)}
        for flavor in flavors:
            if flavor.name not in existing:
                self.nova_client.flavors.create(name=flavor.name,
                                                ram=flavor.ram,
                                                vcpus=flavor.vcpus,
                                                disk=flavor.disk,
                                                swap=flavor.swap,
                                                rxtx_factor=flavor.rxtx_factor,
                                                ephemeral=flavor.ephemeral,
                                                is_public=flavor.is_public)

    @log_step(3, LOG)
    def __upload_user_passwords(self, users):
        # upload user password if the user exists both on source and destination
        with sqlalchemy.create_engine(self.keystone_db_conn_url).begin() as connection:
            for user in self.keystone_client.users.list():
                if user.name in users:
                    connection.execute(sqlalchemy.text("UPDATE user SET password = :password WHERE id = :user_id"),
                                       user_id=user.id,
                                       password=users[user.name])