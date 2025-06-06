# --- BEGIN COPYRIGHT BLOCK ---
# Copyright (C) 2025 Red Hat, Inc.
# All rights reserved.
#
# License: GPL (version 3 or any later version).
# See LICENSE for details.
# --- END COPYRIGHT BLOCK ---
#
import pytest
import logging
import time
from lib389.backend import Backend
from lib389.replica import Replicas
from lib389.tasks import *
from lib389.utils import *
from lib389.topologies import topology_m4 as topo_m4
from lib389.topologies import topology_m2 as topo_m2
from . import get_repl_entries
from lib389.idm.user import UserAccount
from lib389.replica import ReplicationManager, Changelog
from lib389._constants import *

pytestmark = pytest.mark.tier0

TEST_ENTRY_NAME = 'mmrepl_test'
TEST_ENTRY_DN = 'uid={},{}'.format(TEST_ENTRY_NAME, DEFAULT_SUFFIX)
NEW_SUFFIX_NAME = 'test_repl'
NEW_SUFFIX = 'o={}'.format(NEW_SUFFIX_NAME)
NEW_BACKEND = 'repl_base'

DEBUGGING = os.getenv("DEBUGGING", default=False)
if DEBUGGING:
    logging.getLogger(__name__).setLevel(logging.DEBUG)
else:
    logging.getLogger(__name__).setLevel(logging.INFO)
log = logging.getLogger(__name__)


@pytest.fixture(scope="function")
def create_entry(topo_m4, request):
    """Add test entry to supplier1"""

    log.info('Adding entry {}'.format(TEST_ENTRY_DN))

    test_user = UserAccount(topo_m4.ms["supplier1"], TEST_ENTRY_DN)
    if test_user.exists():
        log.info('Deleting entry {}'.format(TEST_ENTRY_DN))
        test_user.delete()
    test_user.create(properties={
        'uid': TEST_ENTRY_NAME,
        'cn': TEST_ENTRY_NAME,
        'sn': TEST_ENTRY_NAME,
        'userPassword': TEST_ENTRY_NAME,
        'uidNumber' : '1000',
        'gidNumber' : '2000',
        'homeDirectory' : '/home/mmrepl_test',
    })

@pytest.fixture(scope="function")
def new_suffix(topo_m4, request):
    """Add a new suffix and enable a replication on it"""

    for num in range(1, 5):
        log.info('Adding suffix:{} and backend: {} to supplier{}'.format(NEW_SUFFIX, NEW_BACKEND, num))
        topo_m4.ms["supplier{}".format(num)].backend.create(NEW_SUFFIX, {BACKEND_NAME: NEW_BACKEND})
        topo_m4.ms["supplier{}".format(num)].mappingtree.create(NEW_SUFFIX, NEW_BACKEND)

        try:
            topo_m4.ms["supplier{}".format(num)].add_s(Entry((NEW_SUFFIX, {
                'objectclass': 'top',
                'objectclass': 'organization',
                'o': NEW_SUFFIX_NAME,
                'description': NEW_SUFFIX_NAME
            })))
        except ldap.LDAPError as e:
            log.error('Failed to add suffix ({}): error ({})'.format(NEW_SUFFIX, e.message['desc']))
            raise

    def fin():
        for num in range(1, 5):
            log.info('Deleting suffix:{} and backend: {} from supplier{}'.format(NEW_SUFFIX, NEW_BACKEND, num))
            topo_m4.ms["supplier{}".format(num)].mappingtree.delete(NEW_SUFFIX)
            topo_m4.ms["supplier{}".format(num)].backend.delete(NEW_SUFFIX)

    request.addfinalizer(fin)


def test_add_entry(topo_m4, create_entry):
    """Check that entries are replicated after add operation

    :id: 024250f1-5f7e-4f3b-a9f5-27741e6fd405
    :setup: Four suppliers replication setup, an entry
    :steps:
        1. Check entry on all other suppliers
    :expectedresults:
        1. The entry should be replicated to all suppliers
    """

    entries = get_repl_entries(topo_m4, TEST_ENTRY_NAME, ["uid"])
    assert all(entries), "Entry {} wasn't replicated successfully".format(TEST_ENTRY_DN)


def test_modify_entry(topo_m4, create_entry):
    """Check that entries are replicated after modify operation

    :id: 36764053-622c-43c2-a132-d7a3ab7d9aaa
    :setup: Four suppliers replication setup, an entry
    :steps:
        1. Modify the entry on supplier1 - add attribute
        2. Wait for replication to happen
        3. Check entry on all other suppliers
        4. Modify the entry on supplier1 - replace attribute
        5. Wait for replication to happen
        6. Check entry on all other suppliers
        7. Modify the entry on supplier1 - delete attribute
        8. Wait for replication to happen
        9. Check entry on all other suppliers
    :expectedresults:
        1. Attribute should be successfully added
        2. Some time should pass
        3. The change should be present on all suppliers
        4. Attribute should be successfully replaced
        5. Some time should pass
        6. The change should be present on all suppliers
        7. Attribute should be successfully deleted
        8. Some time should pass
        9. The change should be present on all suppliers
    """
    if DEBUGGING:
        sleep_time = 8
    else:
        sleep_time = 2

    log.info('Modifying entry {} - add operation'.format(TEST_ENTRY_DN))

    m1 = topo_m4.ms["supplier1"]
    m2 = topo_m4.ms["supplier2"]
    m3 = topo_m4.ms["supplier3"]
    m4 = topo_m4.ms["supplier4"]
    repl = ReplicationManager(DEFAULT_SUFFIX)

    test_user = UserAccount(topo_m4.ms["supplier1"], TEST_ENTRY_DN)
    test_user.add('mail', '{}@redhat.com'.format(TEST_ENTRY_NAME))
    repl.wait_for_replication(m1, m2)
    repl.wait_for_replication(m1, m3)
    repl.wait_for_replication(m1, m4)

    all_user = topo_m4.all_get_dsldapobject(TEST_ENTRY_DN, UserAccount)
    for u in all_user:
        assert "{}@redhat.com".format(TEST_ENTRY_NAME) in u.get_attr_vals_utf8('mail')

    log.info('Modifying entry {} - replace operation'.format(TEST_ENTRY_DN))
    test_user.replace('mail', '{}@greenhat.com'.format(TEST_ENTRY_NAME))
    repl.wait_for_replication(m1, m2)
    repl.wait_for_replication(m1, m3)
    repl.wait_for_replication(m1, m4)

    all_user = topo_m4.all_get_dsldapobject(TEST_ENTRY_DN, UserAccount)
    for u in all_user:
        assert "{}@greenhat.com".format(TEST_ENTRY_NAME) in u.get_attr_vals_utf8('mail')

    log.info('Modifying entry {} - delete operation'.format(TEST_ENTRY_DN))
    test_user.remove('mail', '{}@greenhat.com'.format(TEST_ENTRY_NAME))
    repl.wait_for_replication(m1, m2)
    repl.wait_for_replication(m1, m3)
    repl.wait_for_replication(m1, m4)

    all_user = topo_m4.all_get_dsldapobject(TEST_ENTRY_DN, UserAccount)
    for u in all_user:
        assert "{}@greenhat.com".format(TEST_ENTRY_NAME) not in u.get_attr_vals_utf8('mail')


def test_delete_entry(topo_m4, create_entry):
    """Check that entry deletion is replicated after delete operation

    :id: 18437262-9d6a-4b98-a47a-6182501ab9bc
    :setup: Four suppliers replication setup, an entry
    :steps:
        1. Delete the entry from supplier1
        2. Check entry on all other suppliers
    :expectedresults:
        1. The entry should be deleted
        2. The change should be present on all suppliers
    """

    log.info('Deleting entry {} during the test'.format(TEST_ENTRY_DN))
    topo_m4.ms["supplier1"].delete_s(TEST_ENTRY_DN)
    if DEBUGGING:
        time.sleep(8)
    else:
        time.sleep(1)
    entries = get_repl_entries(topo_m4, TEST_ENTRY_NAME, ["uid"])
    assert not entries, "Entry deletion {} wasn't replicated successfully".format(TEST_ENTRY_DN)


@pytest.mark.parametrize("delold", [0, 1])
def test_modrdn_entry(topo_m4, create_entry, delold):
    """Check that entries are replicated after modrdn operation

    :id: 02558e6d-a745-45ae-8d88-34fe9b16adc9
    :parametrized: yes
    :setup: Four suppliers replication setup, an entry
    :steps:
        1. Make modrdn operation on entry on supplier1 with both delold 1 and 0
        2. Check entry on all other suppliers
    :expectedresults:
        1. Modrdn operation should be successful
        2. The change should be present on all suppliers
    """

    newrdn_name = 'newrdn'
    newrdn_dn = 'uid={},{}'.format(newrdn_name, DEFAULT_SUFFIX)
    log.info('Modify entry RDN {}'.format(TEST_ENTRY_DN))
    try:
        topo_m4.ms["supplier1"].modrdn_s(TEST_ENTRY_DN, 'uid={}'.format(newrdn_name), delold)
    except ldap.LDAPError as e:
        log.error('Failed to modrdn entry (%s): error (%s)' % (TEST_ENTRY_DN,
                                                               e.message['desc']))
        raise e

    try:
        entries_new = get_repl_entries(topo_m4, newrdn_name, ["uid"])
        assert all(entries_new), "Entry {} wasn't replicated successfully".format(newrdn_name)
        if delold == 0:
            entries_old = get_repl_entries(topo_m4, TEST_ENTRY_NAME, ["uid"])
            assert all(entries_old), "Entry with old rdn {} wasn't replicated successfully".format(TEST_ENTRY_DN)
        else:
            entries_old = get_repl_entries(topo_m4, TEST_ENTRY_NAME, ["uid"])
            assert not entries_old, "Entry with old rdn {} wasn't removed in replicas successfully".format(
                TEST_ENTRY_DN)
    finally:
        log.info('Remove entry with new RDN {}'.format(newrdn_dn))
        topo_m4.ms["supplier1"].delete_s(newrdn_dn)


def test_modrdn_after_pause(topo_m4):
    """Check that changes are properly replicated after replica pause

    :id: 6271dc9c-a993-4a9e-9c6d-05650cdab282
    :setup: Four suppliers replication setup, an entry
    :steps:
        1. Pause all replicas
        2. Make modrdn operation on entry on supplier1
        3. Resume all replicas
        4. Wait for replication to happen
        5. Check entry on all other suppliers
    :expectedresults:
        1. Replicas should be paused
        2. Modrdn operation should be successful
        3. Replicas should be resumed
        4. Some time should pass
        5. The change should be present on all suppliers
    """

    if DEBUGGING:
        sleep_time = 8
    else:
        sleep_time = 3

    newrdn_name = 'newrdn'
    newrdn_dn = 'uid={},{}'.format(newrdn_name, DEFAULT_SUFFIX)

    log.info('Adding entry {}'.format(TEST_ENTRY_DN))
    try:
        topo_m4.ms["supplier1"].add_s(Entry((TEST_ENTRY_DN, {
            'objectclass': 'top person'.split(),
            'objectclass': 'organizationalPerson',
            'objectclass': 'inetorgperson',
            'cn': TEST_ENTRY_NAME,
            'sn': TEST_ENTRY_NAME,
            'uid': TEST_ENTRY_NAME
        })))
    except ldap.LDAPError as e:
        log.error('Failed to add entry (%s): error (%s)' % (TEST_ENTRY_DN,
                                                            e.message['desc']))
        raise e

    log.info('Pause all replicas')
    topo_m4.pause_all_replicas()

    log.info('Modify entry RDN {}'.format(TEST_ENTRY_DN))
    try:
        topo_m4.ms["supplier1"].modrdn_s(TEST_ENTRY_DN, 'uid={}'.format(newrdn_name))
    except ldap.LDAPError as e:
        log.error('Failed to modrdn entry (%s): error (%s)' % (TEST_ENTRY_DN,
                                                               e.message['desc']))
        raise e

    log.info('Resume all replicas')
    topo_m4.resume_all_replicas()

    log.info('Wait for replication to happen')
    time.sleep(sleep_time)

    try:
        entries_new = get_repl_entries(topo_m4, newrdn_name, ["uid"])
        assert all(entries_new), "Entry {} wasn't replicated successfully".format(newrdn_name)
    finally:
        log.info('Remove entry with new RDN {}'.format(newrdn_dn))
        topo_m4.ms["supplier1"].delete_s(newrdn_dn)


def test_modify_stripattrs(topo_m4):
    """Check that we can modify nsds5replicastripattrs

    :id: f36abed8-e262-4f35-98aa-71ae55611aaa
    :setup: Four suppliers replication setup
    :steps:
        1. Modify nsds5replicastripattrs attribute on any agreement
        2. Search for the modified attribute
    :expectedresults: It should be contain the value
        1. nsds5replicastripattrs should be successfully set
        2. The modified attribute should be the one we set
    """

    m1 = topo_m4.ms["supplier1"]
    agreement = m1.agreement.list(suffix=DEFAULT_SUFFIX)[0].dn
    attr_value = b'modifiersname modifytimestamp'

    log.info('Modify nsds5replicastripattrs with {}'.format(attr_value))
    m1.modify_s(agreement, [(ldap.MOD_REPLACE, 'nsds5replicastripattrs', [attr_value])])

    log.info('Check nsds5replicastripattrs for {}'.format(attr_value))
    entries = m1.search_s(agreement, ldap.SCOPE_BASE, "objectclass=*", ['nsds5replicastripattrs'])
    assert attr_value in entries[0].data['nsds5replicastripattrs']


def test_multi_subsuffix_replication(topo_m4):
    """Check that replication works with multiple subsuffixes

    :id: ac1aaeae-173e-48e7-847f-03b9867443c4
    :setup: Four suppliers replication setup
    :steps:
        1. Create additional suffixes
        2. Setup replication for all suppliers
        3. Generate test data for each suffix (add, modify, remove)
        4. Wait for replication to complete across all suppliers for each suffix
        5. Check that all expected data is present on all suppliers
    :expectedresults:
        1. Success
        2. Success
        3. Success
        4. Success
        5. Success (the data is replicated everywhere)
    """

    SUFFIX_2 = "dc=test2"
    SUFFIX_3 = f"dc=test3,{DEFAULT_SUFFIX}"
    all_suffixes = [DEFAULT_SUFFIX, SUFFIX_2, SUFFIX_3]

    test_users_by_suffix = {suffix: [] for suffix in all_suffixes}
    created_backends = []

    suppliers = [
        topo_m4.ms["supplier1"],
        topo_m4.ms["supplier2"],
        topo_m4.ms["supplier3"],
        topo_m4.ms["supplier4"]
    ]

    try:
        # Setup additional backends and replication for the new suffixes
        for suffix in [SUFFIX_2, SUFFIX_3]:
            repl = ReplicationManager(suffix)
            for supplier in suppliers:
                # Create a new backend for this suffix
                props = {
                    'cn': f'userRoot_{suffix.split(",")[0][3:]}',
                    'nsslapd-suffix': suffix
                }
                be = Backend(supplier)
                be.create(properties=props)
                be.create_sample_entries('001004002')

                # Track the backend so we can remove it later
                created_backends.append((supplier, props['cn']))

                # Enable replication
                if supplier == suppliers[0]:
                    repl.create_first_supplier(supplier)
                else:
                    repl.join_supplier(suppliers[0], supplier)

            # Create a full mesh topology for this suffix
            for i, supplier_i in enumerate(suppliers):
                for j, supplier_j in enumerate(suppliers):
                    if i != j:
                        repl.ensure_agreement(supplier_i, supplier_j)

        # Generate test data for each suffix (add, modify, remove)
        for suffix in all_suffixes:
            # Create some user entries in supplier1
            for i in range(20):
                user_dn = f'uid=test_user_{i},{suffix}'
                test_user = UserAccount(suppliers[0], user_dn)
                test_user.create(properties={
                    'uid': f'test_user_{i}',
                    'cn': f'Test User {i}',
                    'sn': f'User{i}',
                    'userPassword': 'password',
                    'uidNumber': str(1000 + i),
                    'gidNumber': '2000',
                    'homeDirectory': f'/home/test_user_{i}'
                })
                test_users_by_suffix[suffix].append(test_user)

            # Perform modifications on these entries
            for user in test_users_by_suffix[suffix]:
                # Add some attributes
                for j in range(3):
                    user.add('description', f'Description {j}')
                # Replace an attribute
                user.replace('cn', f'Modified User {user.get_attr_val_utf8("uid")}')
                # Delete the attributes we added
                for j in range(3):
                    try:
                        user.remove('description', f'Description {j}')
                    except Exception:
                        pass

        # Wait for replication to complete across all suppliers, for each suffix
        for suffix in all_suffixes:
            repl = ReplicationManager(suffix)
            for i, supplier_i in enumerate(suppliers):
                for j, supplier_j in enumerate(suppliers):
                    if i != j:
                        repl.wait_for_replication(supplier_i, supplier_j)

        # Verify that each user and modification replicated to all suppliers
        for suffix in all_suffixes:
            for i in range(20):
                user_dn = f'uid=test_user_{i},{suffix}'
                # Retrieve this user from all suppliers
                all_user_objs = topo_m4.all_get_dsldapobject(user_dn, UserAccount)
                # Ensure it exists in all 4 suppliers
                assert len(all_user_objs) == 4, (
                    f"User {user_dn} not found on all suppliers. "
                    f"Found only on {len(all_user_objs)} suppliers."
                )
                # Check modifications: 'cn' should now be 'Modified User test_user_{i}'
                for user_obj in all_user_objs:
                    expected_cn = f"Modified User test_user_{i}"
                    actual_cn = user_obj.get_attr_val_utf8("cn")
                    assert actual_cn == expected_cn, (
                        f"User {user_dn} has unexpected 'cn': {actual_cn} "
                        f"(expected '{expected_cn}') on supplier {user_obj._instance.serverid}"
                    )
                    # And check that 'description' attributes were removed
                    desc_vals = user_obj.get_attr_vals_utf8('description')
                    for j in range(3):
                        assert f"Description {j}" not in desc_vals, (
                            f"User {user_dn} on supplier {user_obj._instance.serverid} "
                            f"still has 'Description {j}'"
                        )

        # Check there are no decoding errors
        assert not topo_m4.ms["supplier1"].ds_error_log.match('.*decoding failed.*')
        assert not topo_m4.ms["supplier2"].ds_error_log.match('.*decoding failed.*')
        assert not topo_m4.ms["supplier3"].ds_error_log.match('.*decoding failed.*')
        assert not topo_m4.ms["supplier4"].ds_error_log.match('.*decoding failed.*')

    finally:
        for suffix, test_users in test_users_by_suffix.items():
            for user in test_users:
                try:
                    if user.exists():
                        user.delete()
                except Exception:
                    pass

        for suffix in [SUFFIX_2, SUFFIX_3]:
            repl = ReplicationManager(suffix)
            for supplier in suppliers:
                try:
                    repl.remove_supplier(supplier)
                except Exception:
                    pass

        for (supplier, backend_name) in created_backends:
            be = Backend(supplier, backend_name)
            try:
                be.delete()
            except Exception:
                pass


def test_new_suffix(topo_m4, new_suffix):
    """Check that we can enable replication on a new suffix

    :id: d44a9ed4-26b0-4189-b0d0-b2b336ddccbd
    :setup: Four suppliers replication setup, a new suffix
    :steps:
        1. Enable replication on the new suffix
        2. Check if replication works
        3. Disable replication on the new suffix
    :expectedresults:
        1. Replication on the new suffix should be enabled
        2. Replication should work
        3. Replication on the new suffix should be disabled
    """
    m1 = topo_m4.ms["supplier1"]
    m2 = topo_m4.ms["supplier2"]

    repl = ReplicationManager(NEW_SUFFIX)

    repl.create_first_supplier(m1)

    repl.join_supplier(m1, m2)

    repl.test_replication(m1, m2)
    repl.test_replication(m2, m1)

    repl.remove_supplier(m1)
    repl.remove_supplier(m2)


def test_many_attrs(topo_m4, create_entry):
    """Check a replication with many attributes (add and delete)

    :id: d540b358-f67a-43c6-8df5-7c74b3cb7523
    :setup: Four suppliers replication setup, a test entry
    :steps:
        1. Add 10 new attributes to the entry
        2. Delete few attributes: one from the beginning,
           two from the middle and one from the end
        3. Check that the changes were replicated in the right order
    :expectedresults:
        1. The attributes should be successfully added
        2. Delete operations should be successful
        3. The changes should be replicated in the right order
    """

    m1 = topo_m4.ms["supplier1"]
    add_list = ensure_list_bytes(map(lambda x: "test{}".format(x), range(10)))
    delete_list = ensure_list_bytes(map(lambda x: "test{}".format(x), [0, 4, 7, 9]))
    test_user = UserAccount(topo_m4.ms["supplier1"], TEST_ENTRY_DN)

    log.info('Modifying entry {} - 10 add operations'.format(TEST_ENTRY_DN))
    for add_name in add_list:
        test_user.add('description', add_name)

    if DEBUGGING:
        time.sleep(10)
    else:
        time.sleep(1)

    log.info('Check that everything was properly replicated after an add operation')
    entries = get_repl_entries(topo_m4, TEST_ENTRY_NAME, ["description"])
    for entry in entries:
        assert all(entry.getValues("description")[i] == add_name for i, add_name in enumerate(add_list))

    log.info('Modifying entry {} - 4 delete operations for {}'.format(TEST_ENTRY_DN, str(delete_list)))
    for delete_name in delete_list:
        test_user.remove('description', delete_name)

    if DEBUGGING:
        time.sleep(10)
    else:
        time.sleep(1)

    log.info('Check that everything was properly replicated after a delete operation')
    entries = get_repl_entries(topo_m4, TEST_ENTRY_NAME, ["description"])
    for entry in entries:
        for i, value in enumerate(entry.getValues("description")):
            assert value == [name for name in add_list if name not in delete_list][i]
            assert value not in delete_list


def test_double_delete(topo_m4, create_entry):
    """Check that double delete of the entry doesn't crash server

    :id: 5b85a5af-df29-42c7-b6cb-965ec5aa478e
    :feature: Multi supplier replication
    :setup: Four suppliers replication setup, a test entry
    :steps: 1. Delete the entry
            2. Delete the entry on the second supplier
            3. Check that server is alive
    :expectedresults: Server hasn't crash
    """

    log.info('Deleting entry {} from supplier1'.format(TEST_ENTRY_DN))
    topo_m4.ms["supplier1"].delete_s(TEST_ENTRY_DN)

    if DEBUGGING:
        time.sleep(5)
    else:
        time.sleep(1)

    log.info('Deleting entry {} from supplier2'.format(TEST_ENTRY_DN))
    try:
        topo_m4.ms["supplier2"].delete_s(TEST_ENTRY_DN)
    except ldap.NO_SUCH_OBJECT:
        log.info("Entry {} wasn't found supplier2. It is expected.".format(TEST_ENTRY_DN))

    if DEBUGGING:
        time.sleep(5)
    else:
        time.sleep(1)

    log.info('Make searches to check if server is alive')
    entries = get_repl_entries(topo_m4, TEST_ENTRY_NAME, ["uid"])
    assert not entries, "Entry deletion {} wasn't replicated successfully".format(TEST_ENTRY_DN)


def test_password_repl_error(topo_m4, create_entry):
    """Check that error about userpassword replication is properly logged

    :id: d4f12dc0-cd2c-4b92-9b8d-d764a60f0698
    :feature: Multi supplier replication
    :setup: Four suppliers replication setup, a test entry
    :steps: 1. Change userpassword on supplier 1
            2. Restart the servers to flush the logs
            3. Check the error log for an replication error
    :expectedresults: We don't have a replication error in the error log
    """

    m1 = topo_m4.ms["supplier1"]
    m2 = topo_m4.ms["supplier2"]
    m3 = topo_m4.ms["supplier3"]
    m4 = topo_m4.ms["supplier4"]
    TEST_ENTRY_NEW_PASS = 'new_{}'.format(TEST_ENTRY_NAME)

    log.info('Clean the error log')
    m2.deleteErrorLogs()

    log.info('Set replication loglevel')
    m1.config.loglevel((ErrorLog.REPLICA,))
    m2.config.loglevel((ErrorLog.REPLICA,))
    m3.config.loglevel((ErrorLog.REPLICA,))
    m4.config.loglevel((ErrorLog.REPLICA,))


    log.info('Modifying entry {} - change userpassword on supplier 2'.format(TEST_ENTRY_DN))
    test_user_m1 = UserAccount(topo_m4.ms["supplier1"], TEST_ENTRY_DN)
    test_user_m2 = UserAccount(topo_m4.ms["supplier2"], TEST_ENTRY_DN)
    test_user_m3 = UserAccount(topo_m4.ms["supplier3"], TEST_ENTRY_DN)
    test_user_m4 = UserAccount(topo_m4.ms["supplier4"], TEST_ENTRY_DN)

    test_user_m1.set('userpassword', TEST_ENTRY_NEW_PASS)

    log.info('Restart the servers to flush the logs')
    for num in range(1, 5):
        topo_m4.ms["supplier{}".format(num)].restart(timeout=10)

    m1_conn = test_user_m1.bind(TEST_ENTRY_NEW_PASS)
    m2_conn = test_user_m2.bind(TEST_ENTRY_NEW_PASS)
    m3_conn = test_user_m3.bind(TEST_ENTRY_NEW_PASS)
    m4_conn = test_user_m4.bind(TEST_ENTRY_NEW_PASS)

    if DEBUGGING:
        time.sleep(5)
    else:
        time.sleep(1)

    log.info('Check the error log for the error with {}'.format(TEST_ENTRY_DN))
    assert not m2.ds_error_log.match('.*can.t add a change for uid={}.*'.format(TEST_ENTRY_NAME))


def test_invalid_agmt(topo_m4):
    """Test adding that an invalid agreement is properly rejected and does not crash the server

    :id: 92f10f46-1be1-49ca-9358-784359397bc2
    :setup: MMR with four suppliers
    :steps:
        1. Add invalid agreement (nsds5ReplicaEnabled set to invalid value)
        2. Verify the server is still running
    :expectedresults:
        1. Invalid repl agreement should be rejected
        2. Server should be still running
    """
    m1 = topo_m4.ms["supplier1"]

    # Add invalid agreement (nsds5ReplicaEnabled set to invalid value)
    AGMT_DN = 'cn=whatever,cn=replica,cn="dc=example,dc=com",cn=mapping tree,cn=config'
    try:
        invalid_props = {RA_ENABLED: 'True',  # Invalid value
                         RA_SCHEDULE: '0001-2359 0123456'}
        m1.agreement.create(suffix=DEFAULT_SUFFIX, host='localhost', port=389, properties=invalid_props)
    except ldap.UNWILLING_TO_PERFORM:
        m1.log.info('Invalid repl agreement correctly rejected')
    except ldap.LDAPError as e:
        m1.log.fatal('Got unexpected error adding invalid agreement: ' + str(e))
        assert False
    else:
        m1.log.fatal('Invalid agreement was incorrectly accepted by the server')
        assert False

    # Verify the server is still running
    try:
        m1.simple_bind_s(DN_DM, PASSWORD)
    except ldap.LDAPError as e:
        m1.log.fatal('Failed to bind: ' + str(e))
        assert False


def test_warning_for_invalid_replica(topo_m4):
    """Testing logs to indicate the inconsistency when configuration is performed.

    :id: dd689d03-69b8-4bf9-a06e-2acd19d5e2c8
    :setup: MMR with four suppliers
    :steps:
        1. Setup nsds5ReplicaBackoffMin to 20
        2. Setup nsds5ReplicaBackoffMax to 10
    :expectedresults:
        1. nsds5ReplicaBackoffMin should set to 20
        2. An error should be generated and also logged in the error logs.
    """
    replicas = Replicas(topo_m4.ms["supplier1"])
    replica = replicas.list()[0]
    log.info('Set nsds5ReplicaBackoffMin to 20')
    replica.set('nsds5ReplicaBackoffMin', '20')
    with pytest.raises(ldap.UNWILLING_TO_PERFORM):
        log.info('Set nsds5ReplicaBackoffMax to 10')
        replica.set('nsds5ReplicaBackoffMax', '10')
    log.info('Resetting configuration: nsds5ReplicaBackoffMin')
    replica.remove_all('nsds5ReplicaBackoffMin')
    log.info('Check the error log for the error')
    assert topo_m4.ms["supplier1"].ds_error_log.match('.*nsds5ReplicaBackoffMax.*10.*invalid.*')


def test_csnpurge_large_valueset(topo_m2):
    """Test csn generator test

    :id: 63e2bdb2-0a8f-4660-9465-7b80a9f72a74
    :setup: MMR with 2 suppliers
    :steps:
        1. Create a test_user
        2. add a large set of values (more than 10)
        3. delete all the values (more than 10)
        4. configure the replica to purge those values (purgedelay=5s)
        5. Waiting for 6 second
        6. do a series of update
    :expectedresults:
        1. Should succeeds
        2. Should succeeds
        3. Should succeeds
        4. Should succeeds
        5. Should succeeds
        6. Should not crash
    """
    m1 = topo_m2.ms["supplier2"]

    test_user = UserAccount(m1, TEST_ENTRY_DN)
    if test_user.exists():
        log.info('Deleting entry {}'.format(TEST_ENTRY_DN))
        test_user.delete()
    test_user.create(properties={
        'uid': TEST_ENTRY_NAME,
        'cn': TEST_ENTRY_NAME,
        'sn': TEST_ENTRY_NAME,
        'userPassword': TEST_ENTRY_NAME,
        'uidNumber' : '1000',
        'gidNumber' : '2000',
        'homeDirectory' : '/home/mmrepl_test',
    })

    # create a large value set so that it is sorted
    for i in range(1,20):
        test_user.add('description', 'value {}'.format(str(i)))

    # delete all values of the valueset
    for i in range(1,20):
        test_user.remove('description', 'value {}'.format(str(i)))

    # set purging delay to 5 second and wait more that 5second
    replicas = Replicas(m1)
    replica = replicas.list()[0]
    log.info('nsds5ReplicaPurgeDelay to 5')
    replica.set('nsds5ReplicaPurgeDelay', '5')
    time.sleep(10)

    # add some new values to the valueset containing entries that should be purged
    for i in range(21,25):
        test_user.add('description', 'value {}'.format(str(i)))

def test_urp_trigger_substring_search(topo_m2):
    """Test that a ADD of a entry with a '*' in its DN, triggers
    an internal search with a escaped DN

    :id: 9869bb39-419f-42c3-a44b-c93eb0b77667
    :customerscenario: True
    :setup: MMR with 2 suppliers
    :steps:
        1. enable internal operation loggging for plugins
        2. Create on M1 a test_user with a '*' in its DN
        3. Check the test_user is replicated
        4. Check in access logs that the internal search does not contain '*'
    :expectedresults:
        1. Should succeeds
        2. Should succeeds
        3. Should succeeds
        4. Should succeeds
    """
    m1 = topo_m2.ms["supplier1"]
    m2 = topo_m2.ms["supplier2"]

    # Enable loggging of internal operation logging to capture URP intop
    log.info('Set nsslapd-plugin-logging to on')
    for inst in (m1, m2):
        inst.config.loglevel([AccessLog.DEFAULT, AccessLog.INTERNAL], service='access')
        inst.config.set('nsslapd-plugin-logging', 'on')
        inst.restart()

    # add a user with a DN containing '*'
    test_asterisk_uid = 'asterisk_*_in_value'
    test_asterisk_dn = 'uid={},{}'.format(test_asterisk_uid, DEFAULT_SUFFIX)

    test_user = UserAccount(m1, test_asterisk_dn)
    if test_user.exists():
        log.info('Deleting entry {}'.format(test_asterisk_dn))
        test_user.delete()
    test_user.create(properties={
        'uid': test_asterisk_uid,
        'cn': test_asterisk_uid,
        'sn': test_asterisk_uid,
        'userPassword': test_asterisk_uid,
        'uidNumber' : '1000',
        'gidNumber' : '2000',
        'homeDirectory' : '/home/asterisk',
    })

    # check that the ADD was replicated on M2
    test_user_m2 = UserAccount(m2, test_asterisk_dn)
    for i in range(1,5):
        if test_user_m2.exists():
            break
        else:
            log.info('Entry not yet replicated on M2, wait a bit')
            time.sleep(3)

    # check that M2 access logs does not "(&(objectclass=nstombstone)(nscpentrydn=uid=asterisk_*_in_value,dc=example,dc=com))"
    log.info('Check that on M2, URP as not triggered such internal search')
    pattern = ".*\(Internal\).*SRCH.*\(&\(objectclass=nstombstone\)\(nscpentrydn=uid=asterisk_\*_in_value,dc=example,dc=com.*"
    found = m2.ds_access_log.match(pattern)
    log.info("found line: %s" % found)
    assert not found


@pytest.mark.skipif(ds_is_older('1.4.4'), reason="Not implemented")
def test_csngen_task(topo_m2):
    """Test csn generator test

    :id: b976849f-dbed-447e-91a7-c877d5d71fd0
    :setup: MMR with 2 suppliers
    :steps:
        1. Create a csngen_test task
        2. Check that debug messages "_csngen_gen_tester_main" are in errors logs
    :expectedresults:
        1. Should succeeds
        2. Should succeeds
    """
    m1 = topo_m2.ms["supplier1"]
    csngen_task = csngenTestTask(m1)
    csngen_task.create(properties={
        'ttl': '300'
    })
    time.sleep(10)
    log.info('Check the error log contains strings showing csn generator is tested')
    assert m1.searchErrorsLog("_csngen_gen_tester_main")


def test_default_cl_trimming_enabled(topo_m2):
    """Check that changelog trimming was enabled by default

    :id: c37b9a28-f961-4867-b8a1-e81edd7f9bf3
    :setup: Supplier Instance
    :steps:
        1. Check changelog has trimming set up by default
    :expectedresults:
        1. Success
    """

    # Set up changelog trimming by default
    cl = Changelog(topo_m2.ms["supplier1"], DEFAULT_SUFFIX)
    assert cl.get_attr_val_utf8("nsslapd-changelogmaxage") == "7d"


if __name__ == '__main__':
    # Run isolated
    # -s for DEBUG mode
    CURRENT_FILE = os.path.realpath(__file__)
    pytest.main("-s %s" % CURRENT_FILE)
