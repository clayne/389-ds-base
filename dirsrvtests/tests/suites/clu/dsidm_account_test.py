# --- BEGIN COPYRIGHT BLOCK ---
# Copyright (C) 2025 Red Hat, Inc.
# All rights reserved.
#
# License: GPL (version 3 or any later version).
# See LICENSE for details.
# --- END COPYRIGHT BLOCK ---
#
import logging
import os
import json
import pytest
import ldap
from lib389 import DEFAULT_SUFFIX
from lib389.cli_idm.account import (
    get_dn,
    lock,
    unlock,
    entry_status,
    subtree_status,
)
from lib389.topologies import topology_st
from lib389.cli_base import FakeArgs
from lib389.utils import ds_is_older
from lib389.idm.user import nsUserAccounts
from . import check_value_in_log_and_reset

pytestmark = pytest.mark.tier0

logging.getLogger(__name__).setLevel(logging.DEBUG)
log = logging.getLogger(__name__)


@pytest.fixture(scope="function")
def create_test_user(topology_st, request):
    log.info('Create test user')
    users = nsUserAccounts(topology_st.standalone, DEFAULT_SUFFIX)
    test_user = users.create_test_user()
    log.info('Created test user: %s', test_user.dn)

    def fin():
        log.info('Delete test user')
        if test_user.exists():
            test_user.delete()

    request.addfinalizer(fin)


@pytest.mark.skipif(ds_is_older("1.4.2"), reason="Not implemented")
def test_dsidm_account_entry_status_with_lock(topology_st, create_test_user):
    """ Test dsidm account entry-status option with account lock/unlock

    :id: d911bbf2-3a65-42a4-ad76-df1114caa396
    :setup: Standalone instance
    :steps:
         1. Create user account
         2. Run dsidm account entry status
         3. Run dsidm account lock
         4. Run dsidm account subtree status
         5. Run dsidm account entry status
         6. Run dsidm account unlock
         7. Run dsidm account subtree status
         8. Run dsidm account entry status
    :expectedresults:
         1. Success
         2. The state message should be Entry State: activated
         3. Success
         4. The state message should be Entry State: directly locked through nsAccountLock
         5. Success
         6. The state message should be Entry State: activated
         7. Success
         8. The state message should be Entry State: activated
    """

    standalone = topology_st.standalone
    users = nsUserAccounts(standalone, DEFAULT_SUFFIX)
    test_user = users.get('test_user_1000')

    entry_list = ['Entry DN: {}'.format(test_user.dn),
                  'Entry Creation Date',
                  'Entry Modification Date']

    state_lock = 'Entry State: directly locked through nsAccountLock'
    state_unlock = 'Entry State: activated'

    lock_msg = 'Entry {} is locked'.format(test_user.dn)
    unlock_msg = 'Entry {} is unlocked'.format(test_user.dn)

    args = FakeArgs()
    args.dn = test_user.dn
    args.json = False
    args.basedn = DEFAULT_SUFFIX
    args.scope = ldap.SCOPE_SUBTREE
    args.filter = "(uid=*)"
    args.become_inactive_on = False
    args.inactive_only = False
    args.json = False

    log.info('Test dsidm account entry-status')
    entry_status(standalone, DEFAULT_SUFFIX, topology_st.logcap.log, args)
    check_value_in_log_and_reset(topology_st, content_list=entry_list,
                                 check_value=state_unlock)

    log.info('Test dsidm account lock')
    lock(standalone, DEFAULT_SUFFIX, topology_st.logcap.log, args)
    check_value_in_log_and_reset(topology_st, check_value=lock_msg)

    log.info('Test dsidm account subtree-status with locked account')
    subtree_status(standalone, DEFAULT_SUFFIX, topology_st.logcap.log, args)
    check_value_in_log_and_reset(topology_st, content_list=entry_list,
                                 check_value=state_lock)

    log.info('Test dsidm account entry-status with locked account')
    entry_status(standalone, DEFAULT_SUFFIX, topology_st.logcap.log, args)
    check_value_in_log_and_reset(topology_st, content_list=entry_list,
                                 check_value=state_lock)

    log.info('Test dsidm account unlock')
    unlock(standalone, DEFAULT_SUFFIX, topology_st.logcap.log, args)
    check_value_in_log_and_reset(topology_st, check_value=unlock_msg)

    log.info('Test dsidm account subtree-status with unlocked account')
    subtree_status(standalone, DEFAULT_SUFFIX, topology_st.logcap.log, args)
    check_value_in_log_and_reset(topology_st, content_list=entry_list,
                                 check_value=state_unlock)

    log.info('Test dsidm account entry-status with unlocked account')
    entry_status(standalone, DEFAULT_SUFFIX, topology_st.logcap.log, args)
    check_value_in_log_and_reset(topology_st, content_list=entry_list,
                                 check_value=state_unlock)


def test_dsidm_account_entry_get_by_dn(topology_st, create_test_user):
    """ Test dsidm account get_dn works with non-json and json

    :id: dd848f67c-9944-48a4-ae5e-98dce4fbc364
    :setup: Standalone instance
    :steps:
        1. Get user by DN (non-json)
        2. Get user by DN (json)
    :expectedresults:
        1. Success
        2. Success
    """

    inst = topology_st.standalone
    user_dn = "uid=test_user_1000,ou=people,dc=example,dc=com"

    args = FakeArgs()
    args.dn = user_dn
    args.json = False
    args.basedn = DEFAULT_SUFFIX
    args.scope = ldap.SCOPE_SUBTREE
    args.filter = "(uid=*)"
    args.become_inactive_on = False
    args.inactive_only = False

    # Test non-json result
    check_val = "homeDirectory: /home/test_user_1000"
    get_dn(inst, DEFAULT_SUFFIX, topology_st.logcap.log, args)
    check_value_in_log_and_reset(topology_st, check_value=check_val)

    # Test json
    args.json = True
    get_dn(inst, DEFAULT_SUFFIX, topology_st.logcap.log, args)

    result = topology_st.logcap.get_raw_outputs()
    json_result = json.loads(result[0])
    assert json_result['dn'] == user_dn


if __name__ == '__main__':
    # Run isolated
    # -s for DEBUG mode
    CURRENT_FILE = os.path.realpath(__file__)
    pytest.main("-s %s" % CURRENT_FILE)
