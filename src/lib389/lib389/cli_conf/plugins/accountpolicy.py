# --- BEGIN COPYRIGHT BLOCK ---
# Copyright (C) 2023 Red Hat, Inc.
# All rights reserved.
#
# License: GPL (version 3 or any later version).
# See LICENSE for details.
# --- END COPYRIGHT BLOCK ---

import ldap
from lib389.plugins import AccountPolicyPlugin, AccountPolicyConfig
from lib389.cli_conf import add_generic_plugin_parsers, generic_object_edit, generic_object_add
from lib389.cli_base import CustomHelpFormatter

arg_to_attr = {
    'config_entry': 'nsslapd-pluginarg0'
}

arg_to_attr_config = {
    'alt_state_attr': 'altstateattrname',
    'always_record_login': 'alwaysRecordLogin',
    'always_record_login_attr': 'alwaysRecordLoginAttr',
    'limit_attr': 'limitattrname',
    'spec_attr': 'specattrname',
    'state_attr': 'stateattrname',
    'login_history': 'lastLoginHistory',
    'login_history_size': 'lastLoginHistorySize',
    'check_all_state_attrs': 'checkallstateattrs'
}


def accountpolicy_edit(inst, basedn, log, args):
    log = log.getChild('accountpolicy_edit')
    plugin = AccountPolicyPlugin(inst)
    generic_object_edit(plugin, log, args, arg_to_attr)


def accountpolicy_add_config(inst, basedn, log, args):
    log = log.getChild('accountpolicy_add_config')
    targetdn = args.DN
    if not ldap.dn.is_dn(targetdn):
        raise ValueError("Specified DN is not a valid DN")
    config = generic_object_add(AccountPolicyConfig, inst, log, args, arg_to_attr_config, dn=targetdn)
    plugin = AccountPolicyPlugin(inst)
    plugin.set('nsslapd-pluginarg0', config.dn)
    log.info('Account Policy attribute nsslapd-pluginarg0 (config_entry) '
             'was set in the main plugin config')


def accountpolicy_edit_config(inst, basedn, log, args):
    log = log.getChild('accountpolicy_edit_config')
    targetdn = args.DN
    if not ldap.dn.is_dn(targetdn):
        raise ValueError("Specified DN is not a valid DN")
    config = AccountPolicyConfig(inst, targetdn)
    generic_object_edit(config, log, args, arg_to_attr_config)


def accountpolicy_show_config(inst, basedn, log, args):
    log = log.getChild('accountpolicy_show_config')
    targetdn = args.DN
    if not ldap.dn.is_dn(targetdn):
        raise ValueError("Specified DN is not a valid DN")
    config = AccountPolicyConfig(inst, targetdn)

    if not config.exists():
        raise ldap.NO_SUCH_OBJECT("Entry %s doesn't exists" % targetdn)
    if args and args.json:
        o_str = config.get_all_attrs_json()

        log.info(o_str)
    else:
        log.info(config.display())


def accountpolicy_del_config(inst, basedn, log, args):
    log = log.getChild('accountpolicy_del_config')
    targetdn = args.DN
    if not ldap.dn.is_dn(targetdn):
        raise ValueError("Specified DN is not a valid DN")
    config = AccountPolicyConfig(inst, targetdn)
    config.delete()
    # Now remove the attribute from the plugin
    plugin = AccountPolicyPlugin(inst)
    plugin.remove_all('nsslapd-pluginConfigArea')
    log.info("Successfully deleted the %s", targetdn)


def _add_parser_args(parser):
    parser.add_argument('--always-record-login', choices=['yes', 'no'], type=str.lower,
                        help='Sets that every entry records its last login time (alwaysRecordLogin)')
    parser.add_argument('--alt-state-attr',
                        help='Provides a backup attribute for the server to reference '
                             'to evaluate the expiration time (altStateAttrName)')
    parser.add_argument('--always-record-login-attr',
                        help='Specifies the attribute to store the time of the last successful '
                             'login in this attribute in the users directory entry (alwaysRecordLoginAttr)')
    parser.add_argument('--limit-attr',
                        help='Specifies the attribute within the policy to use '
                             'for the account inactivation limit (limitAttrName)')
    parser.add_argument('--spec-attr',
                        help='Specifies the attribute to identify which entries '
                             'are account policy configuration entries (specAttrName)')
    parser.add_argument('--state-attr',
                        help='Specifies the primary time attribute used to evaluate an account policy (stateAttrName)')
    parser.add_argument('--login-history-size',
                        help='Specifies the number of login timestamps to store (lastLoginHistSize) )')
    parser.add_argument('--check-all-state-attrs', choices=['yes', 'no'], type=str.lower,
                        help="Check both state and alternate state attributes for account state")


def create_parser(subparsers):
    accountpolicy = subparsers.add_parser('account-policy', help='Manage and configure Account Policy plugin', formatter_class=CustomHelpFormatter)
    subcommands = accountpolicy.add_subparsers(help='action')
    add_generic_plugin_parsers(subcommands, AccountPolicyPlugin)

    edit = subcommands.add_parser('set', help='Edit the plugin settings', formatter_class=CustomHelpFormatter)
    edit.set_defaults(func=accountpolicy_edit)
    edit.add_argument('--config-entry', help='Sets the nsslapd-pluginarg0 attribute')

    config = subcommands.add_parser('config-entry', help='Manage the config entry', formatter_class=CustomHelpFormatter)
    config_subcommands = config.add_subparsers(help='action')

    add_config = config_subcommands.add_parser('add', help='Add the config entry', formatter_class=CustomHelpFormatter)
    add_config.set_defaults(func=accountpolicy_add_config)
    add_config.add_argument('DN', help='The full DN of the config entry')
    _add_parser_args(add_config)

    edit_config = config_subcommands.add_parser('set', help='Edit the config entry', formatter_class=CustomHelpFormatter)
    edit_config.set_defaults(func=accountpolicy_edit_config)
    edit_config.add_argument('DN', help='The full DN of the config entry')
    _add_parser_args(edit_config)

    show_config_parser = config_subcommands.add_parser('show', help='Display the config entry', formatter_class=CustomHelpFormatter)
    show_config_parser.set_defaults(func=accountpolicy_show_config)
    show_config_parser.add_argument('DN', help='The full DN of the config entry')

    del_config_parser = config_subcommands.add_parser('delete',
                                                      help='Delete the config entry and remove the reference in the plugin entry',
                                                      formatter_class=CustomHelpFormatter)
    del_config_parser.set_defaults(func=accountpolicy_del_config)
    del_config_parser.add_argument('DN', help='The full DN of the config entry')
