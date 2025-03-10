/** BEGIN COPYRIGHT BLOCK
 * Copyright (C) 2001 Sun Microsystems, Inc. Used by permission.
 * Copyright (C) 2021 Red Hat, Inc.
 * All rights reserved.
 *
 * License: GPL (version 3 or any later version).
 * See LICENSE for details.
 * END COPYRIGHT BLOCK **/

#ifdef HAVE_CONFIG_H
#include <config.h>
#endif

/* repl5_agmtlist.c */
/*

 Replication agreements are held in object set (objset.c).

*/

#include "repl5.h"
#include <plstr.h>

/* normalized DN */
#define AGMT_CONFIG_BASE "cn=mapping tree,cn=config"
#define CONFIG_FILTER "(objectclass=nsds5replicationagreement)"
#define WINDOWS_CONFIG_FILTER "(objectclass=nsdsWindowsreplicationagreement)"
#define GLOBAL_CONFIG_FILTER "(|" CONFIG_FILTER WINDOWS_CONFIG_FILTER " )"


PRCallOnceType once = {0};
Objset *agmt_set = NULL; /* The set of replication agreements */

typedef struct agmt_wrapper
{
    Repl_Agmt *agmt;
    void *handle;
} agmt_wrapper;


/*
 * Find the replication agreement whose entry DN matches the given DN.
 * Object is returned referenced, so be sure to release it when
 * finished.
 */
Repl_Agmt *
agmtlist_get_by_agmt_name(const Slapi_DN *agmt_name)
{
    Repl_Agmt *ra = NULL;
    Object *ro;

    for (ro = objset_first_obj(agmt_set); NULL != ro;
         ro = objset_next_obj(agmt_set, ro)) {
        ra = (Repl_Agmt *)object_get_data(ro);
        if (agmt_matches_name(ra, agmt_name)) {
            break;
        }
    }
    return ra;
}


static int
agmt_ptr_cmp(Object *ro, const void *arg)
{
    Repl_Agmt *ra;
    Repl_Agmt *provided_ra = (Repl_Agmt *)arg;

    ra = object_get_data(ro);

    if (ra == provided_ra)
        return 0;
    else
        return 1;
}


static int
agmt_dn_cmp(Object *ro, const void *arg)
{
    Repl_Agmt *ra;
    Slapi_DN *sdn = (Slapi_DN *)arg;

    ra = object_get_data(ro);
    return (slapi_sdn_compare(sdn, agmt_get_dn_byref(ra)));
}

void
agmtlist_release_agmt(Repl_Agmt *ra)
{
    Object *ro;

    PR_ASSERT(NULL != agmt_set);
    PR_ASSERT(NULL != ra);

    ro = objset_find(agmt_set, agmt_ptr_cmp, (const void *)ra);
    if (NULL != ro) {
        /*
         * Release twice - once for the reference we got when finding
         * it, and once for the reference we got when we called
         * agmtlist_get_*().
         */
        object_release(ro);
        object_release(ro);
    }
}

int
agmtlist_agmt_exists(const Repl_Agmt *ra)
{
    Object *ro;
    int exists = 0;

    PR_ASSERT(NULL != agmt_set);
    if (!ra) {
        return exists;
    }
    ro = objset_find(agmt_set, agmt_ptr_cmp, (const void *)ra);
    if (ro) {
        exists = 1;
        object_release(ro);
    }
    return exists;
}


/*
 * Note: when we add the new object, we have a reference to it. We hold
 * on to this reference until the agreement is deleted (or until the
 * server is shut down).
 */
int
add_new_agreement(Slapi_Entry *e)
{
    int rc = 0;
    Repl_Agmt *ra = agmt_new_from_entry(e);
    Slapi_DN *replarea_sdn = NULL;
    Replica *replica = NULL;
    Object *ro = NULL;

    /* tell search result handler callback this entry was not sent */
    if (ra == NULL)
        return 1;

    ro = object_new((void *)ra, agmt_delete);
    objset_add_obj(agmt_set, ro);
    object_release(ro); /* Object now owned by objset */

    /* get the replica for this agreement */
    replarea_sdn = agmt_get_replarea(ra);
    if (!replarea_sdn) {
        return 1;
    }
    replica = replica_get_replica_from_dn(replarea_sdn);
    slapi_sdn_free(&replarea_sdn);

    rc = replica_start_agreement(replica, ra);

    return rc;
}

int
id_extended_agreement(Repl_Agmt *agmt __attribute__((unused)), LDAPMod **mods, Slapi_Entry *e)
{
    Slapi_Attr *sattr = NULL;
    char *val = NULL;
    int return_value = 0;
    int i;

    slapi_entry_attr_find(e, "objectclass", &sattr);
    if (sattr) {
        Slapi_Value *sval = NULL;
        const char *oc_val = NULL;
        for (i = slapi_attr_first_value(sattr, &sval);
             i >= 0; i = slapi_attr_next_value(sattr, i, &sval)) {
        	oc_val = slapi_value_get_string(sval);
            if ((0 == strcasecmp(oc_val, "top")) ||
                (0 == strcasecmp(oc_val, "nsds5replicationAgreement"))) {
                continue;
            } else {
                /* the entry has an additional objectclass, accept mods */
                return 1;
            }
        }
    }
    /* This modification could remove an additional objectclass.
     * In the entry we check this mod has already been applied,
     * so check list of mods
     */
    for (i = 0; NULL != mods && NULL != mods[i]; i++) {
        if (strcasecmp(mods[i]->mod_type, "objectclass"))
            continue;
        if (mods[i]->mod_bvalues) {
            int j;
            for (j = 0; mods[i]->mod_bvalues[j]; j++) {
                slapi_ch_free_string(&val);
                val = slapi_berval_get_string_copy(mods[i]->mod_bvalues[j]);
                if ((0 == strcasecmp(val, "top")) ||
                    (0 == strcasecmp(val, "nsds5replicationAgreement"))) {
                    continue;
                } else {
                    /* an additional objectclass was modified */
                    return_value = 1;
                    break;
                }
            }
        }
        break;
    }
    slapi_ch_free_string(&val);
    return return_value;
}

static int
agmtlist_add_callback(Slapi_PBlock *pb,
                      Slapi_Entry *e,
                      Slapi_Entry *entryAfter __attribute__((unused)),
                      int *returncode,
                      char *returntext __attribute__((unused)),
                      void *arg __attribute__((unused)))
{
    int rc;
    slapi_log_err(SLAPI_LOG_REPL, repl_plugin_name, "agmt_add: begin\n");

    rc = add_new_agreement(e);
    if (0 != rc) {
        Slapi_DN *sdn = NULL;
        slapi_pblock_get(pb, SLAPI_TARGET_SDN, &sdn);
        slapi_log_err(SLAPI_LOG_ERR, repl_plugin_name, "agmtlist_add_callback - "
                                                       "Can't start agreement \"%s\"\n",
                      slapi_sdn_get_dn(sdn));
        *returncode = LDAP_UNWILLING_TO_PERFORM;
        return SLAPI_DSE_CALLBACK_ERROR;
    }
    *returncode = LDAP_SUCCESS;
    return SLAPI_DSE_CALLBACK_OK;
}

static int
agmtlist_modify_callback(Slapi_PBlock *pb,
                         Slapi_Entry *entryBefore __attribute__((unused)),
                         Slapi_Entry *e,
                         int *returncode,
                         char *returntext,
                         void *arg __attribute__((unused)))
{
    int i;
    Slapi_DN *sdn = NULL;
    int start_initialize = 0, stop_initialize = 0, cancel_initialize = 0;
    int update_the_schedule = 0; /* do we need to update the repl sched? */
    Repl_Agmt *agmt = NULL;
    LDAPMod **mods;
    char buff[SLAPI_DSE_RETURNTEXT_SIZE];
    char *errortext = returntext ? returntext : buff;
    char *val = NULL;
    int rc = SLAPI_DSE_CALLBACK_OK;
    Slapi_Operation *op;
    void *identity;

    *returncode = LDAP_SUCCESS;

    /* just let internal operations originated from replication plugin to go through */
    slapi_pblock_get(pb, SLAPI_OPERATION, &op);
    slapi_pblock_get(pb, SLAPI_PLUGIN_IDENTITY, &identity);

    if (operation_is_flag_set(op, OP_FLAG_INTERNAL) &&
        (identity == repl_get_plugin_identity(PLUGIN_MULTISUPPLIER_REPLICATION))) {
        goto done;
    }

    slapi_pblock_get(pb, SLAPI_TARGET_SDN, &sdn);
    if (NULL == sdn) {
        slapi_log_err(SLAPI_LOG_ERR, repl_plugin_name,
                      "agmtlist_modify_callback - NULL target dn\n");
        goto done;
    }
    agmt = agmtlist_get_by_agmt_name(sdn);
    if (NULL == agmt) {
        slapi_log_err(SLAPI_LOG_WARNING, repl_plugin_name, "agmtlist_modify_callback - "
                                                           "Received a modification for unknown replication agreement \"%s\"\n",
                      slapi_sdn_get_dn(sdn));
        goto done;
    }

    slapi_pblock_get(pb, SLAPI_MODIFY_MODS, &mods);
    for (i = 0; NULL != mods && NULL != mods[i]; i++) {
        slapi_ch_free_string(&val);
        if (mods[i]->mod_bvalues && mods[i]->mod_bvalues[0]) {
            val = slapi_berval_get_string_copy(mods[i]->mod_bvalues[0]);
        }
        if (slapi_attr_types_equivalent(mods[i]->mod_type, type_nsds5ReplicaInitialize)) {
            /* we don't allow delete attribute operations unless it was issued by
               the replication plugin - handled above */
            if (mods[i]->mod_op & LDAP_MOD_DELETE) {
                slapi_log_err(SLAPI_LOG_ERR, repl_plugin_name, "agmtlist_modify_callback - "
                                                               "Deletion of %s attribute is not allowed\n",
                              type_nsds5ReplicaInitialize);
                *returncode = LDAP_UNWILLING_TO_PERFORM;
                rc = SLAPI_DSE_CALLBACK_ERROR;
                break;
            } else {
                if (val == NULL) {
                    slapi_log_err(SLAPI_LOG_ERR, repl_plugin_name, "agmtlist_modify_callback - "
                                                                   "No value provided for %s attribute\n",
                                  type_nsds5ReplicaInitialize);
                    *returncode = LDAP_UNWILLING_TO_PERFORM;
                    rc = SLAPI_DSE_CALLBACK_ERROR;
                    break;
                }

                /* Start replica initialization */
                if (strcasecmp(val, "start") == 0) {
                    start_initialize = 1;
                } else if (strcasecmp(val, "stop") == 0) {
                    stop_initialize = 1;
                } else if (strcasecmp(val, "cancel") == 0) {
                    cancel_initialize = 1;
                } else {
                    PR_snprintf(errortext, SLAPI_DSE_RETURNTEXT_SIZE,
                                "Invalid value (%s) value supplied for attr (%s); Ignoring ...",
                                val, mods[i]->mod_type);
                    slapi_log_err(SLAPI_LOG_ERR, repl_plugin_name, "agmtlist_modify_callback - %s\n", errortext);
                    *returncode = LDAP_UNWILLING_TO_PERFORM;
                    rc = SLAPI_DSE_CALLBACK_ERROR;
                }
            }
        } else if (slapi_attr_types_equivalent(mods[i]->mod_type,
                                               type_nsds5ReplicaUpdateSchedule)) {
            /*
             * Request to update the replication schedule.  Set a flag so
             * we know to update the schedule later.
             */
            update_the_schedule = 1;
        } else if (slapi_attr_types_equivalent(mods[i]->mod_type,
                                               type_nsds5ReplicaCredentials)) {
            /* New replica credentials */
            if (agmt_set_credentials_from_entry(agmt, e) != 0) {
                slapi_log_err(SLAPI_LOG_ERR, repl_plugin_name, "agmtlist_modify_callback - "
                                                               "Failed to update credentials for agreement %s\n",
                              agmt_get_long_name(agmt));
                *returncode = LDAP_OPERATIONS_ERROR;
                rc = SLAPI_DSE_CALLBACK_ERROR;
            }
        } else if (slapi_attr_types_equivalent(mods[i]->mod_type,
                                               type_nsds5ReplicaBootstrapCredentials)) {
            /* New replica bootstrap credentials */
            if (agmt_set_bootstrap_credentials_from_entry(agmt, e) != 0) {
                slapi_log_err(SLAPI_LOG_ERR, repl_plugin_name, "agmtlist_modify_callback - "
                        "Failed to update bootstrap credentials for agreement %s\n",
                        agmt_get_long_name(agmt));
                *returncode = LDAP_OPERATIONS_ERROR;
                rc = SLAPI_DSE_CALLBACK_ERROR;
            }
        } else if (slapi_attr_types_equivalent(mods[i]->mod_type,
                                               type_nsds5ReplicaTimeout)) {
            /* New replica timeout */
            if (agmt_set_timeout_from_entry(agmt, e) != 0) {
                slapi_log_err(SLAPI_LOG_ERR, repl_plugin_name, "agmtlist_modify_callback - "
                                                               "Failed to update timeout for agreement %s\n",
                              agmt_get_long_name(agmt));
                *returncode = LDAP_OPERATIONS_ERROR;
                rc = SLAPI_DSE_CALLBACK_ERROR;
            }
        } else if (slapi_attr_types_equivalent(mods[i]->mod_type,
                                               type_nsds5ReplicaFlowControlWindow)) {
            /* New replica timeout */
            if (agmt_set_flowcontrolwindow_from_entry(agmt, e) != 0) {
                slapi_log_err(SLAPI_LOG_ERR, repl_plugin_name, "agmtlist_modify_callback - "
                                                               "Failed to update the flow control window for agreement %s\n",
                              agmt_get_long_name(agmt));
                *returncode = LDAP_OPERATIONS_ERROR;
                rc = SLAPI_DSE_CALLBACK_ERROR;
            }
        } else if (slapi_attr_types_equivalent(mods[i]->mod_type,
                                               type_nsds5ReplicaFlowControlPause)) {
            /* New replica timeout */
            if (agmt_set_flowcontrolpause_from_entry(agmt, e) != 0) {
                slapi_log_err(SLAPI_LOG_ERR, repl_plugin_name, "agmtlist_modify_callback - "
                                                               "Failed to update the flow control pause for agreement %s\n",
                              agmt_get_long_name(agmt));
                *returncode = LDAP_OPERATIONS_ERROR;
                rc = SLAPI_DSE_CALLBACK_ERROR;
            }
        } else if (slapi_attr_types_equivalent(mods[i]->mod_type,
                                               type_replicaIgnoreMissingChange)) {
            /* New replica timeout */
            if (agmt_set_ignoremissing_from_entry(agmt, e) != 0) {
                slapi_log_err(SLAPI_LOG_ERR, repl_plugin_name, "agmtlist_modify_callback - "
                                                               "Failed to update the ignorMissingChange attribute for agreement %s\n",
                              agmt_get_long_name(agmt));
                *returncode = LDAP_OPERATIONS_ERROR;
                rc = SLAPI_DSE_CALLBACK_ERROR;
            }
        } else if (slapi_attr_types_equivalent(mods[i]->mod_type,
                                               type_nsds5ReplicaBusyWaitTime)) {
            /* New replica busywaittime */
            if (agmt_set_busywaittime_from_entry(agmt, e) != 0) {
                slapi_log_err(SLAPI_LOG_ERR, repl_plugin_name, "agmtlist_modify_callback -"
                                                               "Failed to update busy wait time for agreement %s\n",
                              agmt_get_long_name(agmt));
                *returncode = LDAP_OPERATIONS_ERROR;
                rc = SLAPI_DSE_CALLBACK_ERROR;
            }
        } else if (slapi_attr_types_equivalent(mods[i]->mod_type,
                                               type_nsds5ReplicaSessionPauseTime)) {
            /* New replica pausetime */
            if (agmt_set_pausetime_from_entry(agmt, e) != 0) {
                slapi_log_err(SLAPI_LOG_ERR, repl_plugin_name, "agmtlist_modify_callback - "
                                                               "Failed to update session pause time for agreement %s\n",
                              agmt_get_long_name(agmt));
                *returncode = LDAP_OPERATIONS_ERROR;
                rc = SLAPI_DSE_CALLBACK_ERROR;
            }
        } else if (slapi_attr_types_equivalent(mods[i]->mod_type,
                                               type_nsds5ReplicaBindDN)) {
            /* New replica Bind DN */
            if (agmt_set_binddn_from_entry(agmt, e) != 0) {
                slapi_log_err(SLAPI_LOG_ERR, repl_plugin_name, "agmtlist_modify_callback-  "
                                                               "Failed to update bind DN for agreement %s\n",
                              agmt_get_long_name(agmt));
                *returncode = LDAP_OPERATIONS_ERROR;
                rc = SLAPI_DSE_CALLBACK_ERROR;
            }
        } else if (slapi_attr_types_equivalent(mods[i]->mod_type,
                                               type_nsds5ReplicaBootstrapBindDN)) {
            /* New bootstrap Bind DN */
            if (agmt_set_bootstrap_binddn_from_entry(agmt, e) != 0) {
                slapi_log_err(SLAPI_LOG_ERR, repl_plugin_name, "agmtlist_modify_callback-  "
                        "Failed to update bind DN for agreement %s\n",
                        agmt_get_long_name(agmt));
                *returncode = LDAP_OPERATIONS_ERROR;
                rc = SLAPI_DSE_CALLBACK_ERROR;
            }

        } else if (slapi_attr_types_equivalent(mods[i]->mod_type, type_nsds5ReplicaHost)) {
            /* New replica host */
            if (agmt_set_host_from_entry(agmt, e) != 0) {
                slapi_log_err(SLAPI_LOG_ERR, repl_plugin_name,
                              "agmtlist_modify_callback - "
                              "Failed to update host for agreement %s\n",
                              agmt_get_long_name(agmt));
                *returncode = LDAP_OPERATIONS_ERROR;
                rc = SLAPI_DSE_CALLBACK_ERROR;
            } else {
                /*
                 * Changing the host invalidates the agmt maxcsn, so remove it.
                 * The next update will add the correct maxcsn back to the agmt/local ruv.
                 */
                agmt_remove_maxcsn(agmt);
            }
        } else if (slapi_attr_types_equivalent(mods[i]->mod_type,
                                               type_nsds5ReplicaPort)) {
            /* New replica port */
            if (agmt_set_port_from_entry(agmt, e) != 0) {
                slapi_log_err(SLAPI_LOG_ERR, repl_plugin_name,
                              "agmtlist_modify_callback - "
                              "Failed to update port for agreement %s\n",
                              agmt_get_long_name(agmt));
                *returncode = LDAP_OPERATIONS_ERROR;
                rc = SLAPI_DSE_CALLBACK_ERROR;
            } else {
                /*
                 * Changing the port invalidates the agmt maxcsn, so remove it.
                 * The next update will add the correct maxcsn back to the agmt/local ruv.
                 */
                agmt_remove_maxcsn(agmt);
            }
        } else if (slapi_attr_types_equivalent(mods[i]->mod_type,
                                               type_nsds5TransportInfo)) {
            /* New Transport info */
            if (agmt_set_transportinfo_from_entry(agmt, e, PR_FALSE /* get default value */) != 0) {
                slapi_log_err(SLAPI_LOG_ERR, repl_plugin_name, "agmtlist_modify_callback - "
                        "Failed to update transport info for agreement %s\n",
                        agmt_get_long_name(agmt));
                *returncode = LDAP_OPERATIONS_ERROR;
                rc = SLAPI_DSE_CALLBACK_ERROR;
            }
        } else if (slapi_attr_types_equivalent(mods[i]->mod_type,
                                               type_nsds5ReplicaBootstrapTransportInfo))
        {
            /* Bootstrap Transport info */
            if (agmt_set_transportinfo_from_entry(agmt, e, PR_TRUE /* get bootstrap value */) != 0) {
                slapi_log_err(SLAPI_LOG_ERR, repl_plugin_name, "agmtlist_modify_callback - "
                        "Failed to update bootstrap transport info for agreement %s\n",
                        agmt_get_long_name(agmt));
                *returncode = LDAP_OPERATIONS_ERROR;
                rc = SLAPI_DSE_CALLBACK_ERROR;
            }
        } else if (slapi_attr_types_equivalent(mods[i]->mod_type,
                                               type_nsds5ReplicaBindMethod)) {
            if (agmt_set_bind_method_from_entry(agmt, e, PR_FALSE /* get default value */) != 0) {
                slapi_log_err(SLAPI_LOG_ERR, repl_plugin_name, "agmtlist_modify_callback - "
                        "Failed to update bind method for agreement %s\n",
                        agmt_get_long_name(agmt));
                *returncode = LDAP_OPERATIONS_ERROR;
                rc = SLAPI_DSE_CALLBACK_ERROR;
            }
        } else if (slapi_attr_types_equivalent(mods[i]->mod_type,
                                               type_nsds5ReplicaBootstrapBindMethod)) {
            /* Bootstrap bind method */
            if (agmt_set_bind_method_from_entry(agmt, e, PR_TRUE /* get bootstrap value */) != 0) {
                slapi_log_err(SLAPI_LOG_ERR, repl_plugin_name, "agmtlist_modify_callback - "
                        "Failed to update bootstrap bind method for agreement %s\n",
                        agmt_get_long_name(agmt));
                *returncode = LDAP_OPERATIONS_ERROR;
                rc = SLAPI_DSE_CALLBACK_ERROR;
            }
        } else if (slapi_attr_types_equivalent(mods[i]->mod_type,
                                               type_nsds5ReplicatedAttributeList)) {
            char **denied_attrs = NULL;
            /* New set of excluded attributes */
            if (agmt_set_replicated_attributes_from_entry(agmt, e) != 0) {
                slapi_log_err(SLAPI_LOG_ERR, repl_plugin_name, "agmtlist_modify_callback - "
                                                               "Failed to update replicated attributes for agreement %s\n",
                              agmt_get_long_name(agmt));
                *returncode = LDAP_OPERATIONS_ERROR;
                rc = SLAPI_DSE_CALLBACK_ERROR;
            }
            /* Check that there are no verboten attributes in the exclude list */
            denied_attrs = agmt_validate_replicated_attributes(agmt, 0 /* incremental */);
            if (denied_attrs) {
                /* Report the error to the client */
                PR_snprintf(errortext, SLAPI_DSE_RETURNTEXT_SIZE, "attempt to exclude an illegal attribute in a fractional agreement");
                slapi_log_err(SLAPI_LOG_ERR, repl_plugin_name, "agmtlist_modify_callback - "
                                                               "Attempt to exclude an illegal attribute in a fractional agreement\n");

                *returncode = LDAP_UNWILLING_TO_PERFORM;
                rc = SLAPI_DSE_CALLBACK_ERROR;
                /* Free the deny list if we got one */
                slapi_ch_array_free(denied_attrs);
                break;
            }
        } else if (slapi_attr_types_equivalent(mods[i]->mod_type,
                                               type_nsds5ReplicatedAttributeListTotal)) {
            char **denied_attrs = NULL;
            /* New set of excluded attributes */
            if (agmt_set_replicated_attributes_total_from_entry(agmt, e) != 0) {
                slapi_log_err(SLAPI_LOG_ERR, repl_plugin_name, "agmtlist_modify_callback - "
                                                               "Failed to update total update replicated attributes for agreement %s\n",
                              agmt_get_long_name(agmt));
                *returncode = LDAP_OPERATIONS_ERROR;
                rc = SLAPI_DSE_CALLBACK_ERROR;
            }
            /* Check that there are no verboten attributes in the exclude list */
            denied_attrs = agmt_validate_replicated_attributes(agmt, 1 /* total */);
            if (denied_attrs) {
                /* Report the error to the client */
                PR_snprintf(errortext, SLAPI_DSE_RETURNTEXT_SIZE, "attempt to exclude an illegal total update "
                                                                  "attribute in a fractional agreement");
                slapi_log_err(SLAPI_LOG_ERR, repl_plugin_name, "agmtlist_modify_callback - "
                                                               "Attempt to exclude an illegal total update attribute in a fractional agreement\n");

                *returncode = LDAP_UNWILLING_TO_PERFORM;
                rc = SLAPI_DSE_CALLBACK_ERROR;
                /* Free the deny list if we got one */
                slapi_ch_array_free(denied_attrs);
                break;
            }
        } else if (slapi_attr_types_equivalent(mods[i]->mod_type,
                                               "nsds5debugreplicatimeout")) {
            char *timeout_val = (char *)slapi_entry_attr_get_ref(e, "nsds5debugreplicatimeout");
            repl5_set_debug_timeout(timeout_val);
        } else if (slapi_attr_is_last_mod(mods[i]->mod_type) ||
                   strcasecmp(mods[i]->mod_type, "description") == 0) {
            /* ignore modifier's name and timestamp attributes and the description. */
            continue;
        } else if (slapi_attr_types_equivalent(mods[i]->mod_type, type_nsds5ReplicaEnabled)) {
            if (agmt_set_enabled_from_entry(agmt, e, returntext) != 0) {
                slapi_log_err(SLAPI_LOG_ERR, repl_plugin_name, "agmtlist_modify_callback - "
                                                               "Failed to set replica agmt state \"enabled/disabled\" for %s\n",
                              agmt_get_long_name(agmt));
                *returncode = LDAP_OPERATIONS_ERROR;
                rc = SLAPI_DSE_CALLBACK_ERROR;
            }
        } else if (slapi_attr_types_equivalent(mods[i]->mod_type, type_nsds5ReplicaStripAttrs)) {
            if (agmt_set_attrs_to_strip(agmt, e) != 0) {
                slapi_log_err(SLAPI_LOG_ERR, repl_plugin_name, "agmtlist_modify_callback - "
                                                               "Failed to set replica agmt attributes to strip for %s\n",
                              agmt_get_long_name(agmt));
                *returncode = LDAP_OPERATIONS_ERROR;
                rc = SLAPI_DSE_CALLBACK_ERROR;
            }
        } else if (slapi_attr_types_equivalent(mods[i]->mod_type, type_replicaProtocolTimeout)) {
            if (mods[i]->mod_op & LDAP_MOD_DELETE) {
                agmt_set_protocol_timeout(agmt, 0);
            } else {
                long ptimeout = 0;

                if (val) {
                    ptimeout = atol(val);
                }
                if (ptimeout <= 0) {
                    *returncode = LDAP_UNWILLING_TO_PERFORM;
                    PR_snprintf(returntext, SLAPI_DSE_RETURNTEXT_SIZE,
                                "attribute %s value (%s) is invalid, must be a number greater than zero.\n",
                                type_replicaProtocolTimeout, val ? val : "");
                    slapi_log_err(SLAPI_LOG_ERR, repl_plugin_name, "agmtlist_modify_callback - "
                                                                   "Attribute %s value (%s) is invalid, must be a number greater than zero.\n",
                                  type_replicaProtocolTimeout, val ? val : "");
                    rc = SLAPI_DSE_CALLBACK_ERROR;
                    break;
                }
                agmt_set_protocol_timeout(agmt, ptimeout);
            }
        } else if (slapi_attr_types_equivalent(mods[i]->mod_type, type_nsds5WaitForAsyncResults)) {
            if (mods[i]->mod_op & LDAP_MOD_DELETE) {
                (void)agmt_set_WaitForAsyncResults(agmt, NULL);
            } else {
                (void)agmt_set_WaitForAsyncResults(agmt, e);
            }
        } else if ((0 == windows_handle_modify_agreement(agmt, mods[i]->mod_type, e)) &&
                   (0 == id_extended_agreement(agmt, mods, e))) {
            slapi_log_err(SLAPI_LOG_ERR, repl_plugin_name, "agmtlist_modify_callback - "
                                                           "Modification of %s attribute is not allowed\n",
                          mods[i]->mod_type);
            *returncode = LDAP_UNWILLING_TO_PERFORM;
            rc = SLAPI_DSE_CALLBACK_ERROR;
            break;
        }
    }

    if (stop_initialize) {
        agmt_stop(agmt);
    } else if (start_initialize) {
        if (agmt_initialize_replica(agmt) != 0) {
            /* The suffix/repl agmt is disabled */
            agmt_set_last_init_status(agmt, 0, NSDS50_REPL_DISABLED, 0, NULL);
            if (agmt_is_enabled(agmt)) {
                PR_snprintf(returntext, SLAPI_DSE_RETURNTEXT_SIZE, "Suffix is disabled");
            } else {
                PR_snprintf(returntext, SLAPI_DSE_RETURNTEXT_SIZE, "Replication agreement is disabled");
            }
            *returncode = LDAP_UNWILLING_TO_PERFORM;
            rc = SLAPI_DSE_CALLBACK_ERROR;
        }
    } else if (cancel_initialize) {
        agmt_replica_init_done(agmt);
    }

    if (update_the_schedule) {
        if (agmt_set_schedule_from_entry(agmt, e) != 0) {
            slapi_log_err(SLAPI_LOG_ERR, repl_plugin_name, "agmtlist_modify_callback - "
                                                           "Failed to update replication schedule for agreement %s\n",
                          agmt_get_long_name(agmt));
            *returncode = LDAP_OPERATIONS_ERROR;
            rc = SLAPI_DSE_CALLBACK_ERROR;
        }
    }

done:
    if (NULL != agmt) {
        agmtlist_release_agmt(agmt);
    }
    slapi_ch_free_string(&val);

    return rc;
}

static int
agmtlist_delete_callback(Slapi_PBlock *pb __attribute__((unused)),
                         Slapi_Entry *e,
                         Slapi_Entry *entryAfter __attribute__((unused)),
                         int *returncode,
                         char *returntext __attribute__((unused)),
                         void *arg __attribute__((unused)))
{
    Repl_Agmt *ra;
    Object *ro;

    slapi_log_err(SLAPI_LOG_REPL, repl_plugin_name, "agmtlist_delete_callback - Begin\n");
    ro = objset_find(agmt_set, agmt_dn_cmp, (const void *)slapi_entry_get_sdn_const(e));
    ra = (NULL == ro) ? NULL : (Repl_Agmt *)object_get_data(ro);
    if (NULL == ra) {
        slapi_log_err(SLAPI_LOG_ERR, repl_plugin_name, "agmtlist_delete_callback - "
                                                       "Tried to delete replication agreement \"%s\", but no such "
                                                       "agreement was configured.\n",
                      slapi_sdn_get_dn(slapi_entry_get_sdn_const(e)));
    } else {
        agmt_remove_maxcsn(ra); /* remove the agmt maxcsn from the localruv */
        agmt_stop(ra);
        object_release(ro);              /* Release ref acquired in objset_find */
        objset_remove_obj(agmt_set, ro); /* Releases a reference (should be final reference */
    }
    *returncode = LDAP_SUCCESS;
    return SLAPI_DSE_CALLBACK_OK;
}

static int
agmtlist_rename_callback(Slapi_PBlock *pb __attribute__((unused)),
                         Slapi_Entry *entryBefore __attribute__((unused)),
                         Slapi_Entry *e __attribute__((unused)),
                         int *returncode,
                         char *returntext __attribute__((unused)),
                         void *arg __attribute__((unused)))
{
    slapi_log_err(SLAPI_LOG_REPL, repl_plugin_name, "agmtlist_rename_callback - Begin\n");

    *returncode = LDAP_SUCCESS;
    return SLAPI_DSE_CALLBACK_OK;
}


static int
handle_agmt_search(Slapi_Entry *e, void *callback_data)
{
    int *agmtcount = (int *)callback_data;
    int rc;

    slapi_log_err(SLAPI_LOG_REPL, repl_plugin_name,
                  "handle_agmt_search - Found replication agreement named \"%s\".\n",
                  slapi_sdn_get_dn(slapi_entry_get_sdn(e)));
    rc = add_new_agreement(e);
    if (0 == rc) {
        (*agmtcount)++;
    } else {
        slapi_log_err(SLAPI_LOG_REPL, repl_plugin_name, "handle_agmt_search - "
                                                        "The replication agreement named \"%s\" could not be correctly parsed. No "
                                                        "replication will occur with this replica.\n",
                      slapi_sdn_get_dn(slapi_entry_get_sdn(e)));
    }

    return rc;
}


static void
agmtlist_objset_destructor(void **o __attribute__((unused)))
{
    /* XXXggood Nothing to do, I think. */
    return;
}


int
agmtlist_config_init()
{
    Slapi_PBlock *pb;
    int agmtcount = 0;

    agmt_set = objset_new(agmtlist_objset_destructor);

    /* Register callbacks so we're informed about updates */
    slapi_config_register_callback(SLAPI_OPERATION_ADD, DSE_FLAG_PREOP, AGMT_CONFIG_BASE,
                                   LDAP_SCOPE_SUBTREE, GLOBAL_CONFIG_FILTER, agmtlist_add_callback, NULL);
    slapi_config_register_callback(SLAPI_OPERATION_MODIFY, DSE_FLAG_PREOP, AGMT_CONFIG_BASE,
                                   LDAP_SCOPE_SUBTREE, GLOBAL_CONFIG_FILTER, agmtlist_modify_callback, NULL);
    slapi_config_register_callback(SLAPI_OPERATION_DELETE, DSE_FLAG_PREOP, AGMT_CONFIG_BASE,
                                   LDAP_SCOPE_SUBTREE, GLOBAL_CONFIG_FILTER, agmtlist_delete_callback, NULL);
    slapi_config_register_callback(SLAPI_OPERATION_MODRDN, DSE_FLAG_PREOP, AGMT_CONFIG_BASE,
                                   LDAP_SCOPE_SUBTREE, GLOBAL_CONFIG_FILTER, agmtlist_rename_callback, NULL);

    /* Search the DIT and find all the replication agreements */
    pb = slapi_pblock_new();
    slapi_search_internal_set_pb(pb, AGMT_CONFIG_BASE, LDAP_SCOPE_SUBTREE,
                                 GLOBAL_CONFIG_FILTER, NULL /* attrs */, 0 /* attrsonly */,
                                 NULL, /* controls */ NULL /* uniqueid */,
                                 repl_get_plugin_identity(PLUGIN_MULTISUPPLIER_REPLICATION), 0 /* actions */);
    slapi_search_internal_callback_pb(pb,
                                      (void *)&agmtcount /* callback data */,
                                      NULL /* result_callback */,
                                      handle_agmt_search /* search entry cb */,
                                      NULL /* referral callback */);
    slapi_pblock_destroy(pb);

    slapi_log_err(SLAPI_LOG_REPL, repl_plugin_name, "agmtlist_config_init - "
                                                    "Found %d replication agreements in DIT\n",
                  agmtcount);

    return 0;
}


void
agmtlist_shutdown()
{
    Repl_Agmt *ra;
    Object *ro;
    Object *next_ro;

    if (agmt_set == NULL) {
        return;
    }

    ro = objset_first_obj(agmt_set);
    while (NULL != ro) {
        ra = (Repl_Agmt *)object_get_data(ro);
        agmt_stop(ra);
        agmt_update_consumer_ruv(ra);
        agmt_update_init_status(ra);
        next_ro = objset_next_obj(agmt_set, ro);
        /* Object ro was released in objset_next_obj,
         * but the address ro can be still used to remove ro from objset. */
        objset_remove_obj(agmt_set, ro);
        ro = next_ro;
    }
    objset_delete(&agmt_set);
    agmt_set = NULL;
}


/*
 * Notify each replication agreement about an update.
 */
void
agmtlist_notify_all(Slapi_PBlock *pb)
{
    Repl_Agmt *ra;
    Object *ro;

    if (NULL != agmt_set) {
        ro = objset_first_obj(agmt_set);
        while (NULL != ro) {
            ra = (Repl_Agmt *)object_get_data(ro);
            agmt_notify_change(ra, pb);
            ro = objset_next_obj(agmt_set, ro);
        }
    }
}

Object *
agmtlist_get_first_agreement_for_replica(Replica *r)
{
    return agmtlist_get_next_agreement_for_replica(r, NULL);
}

Object *
agmtlist_get_next_agreement_for_replica(Replica *r, Object *prev)
{
    const Slapi_DN *replica_root;
    Slapi_DN *agmt_root;
    Object *obj;
    Repl_Agmt *agmt;

    if (r == NULL) {
        /* ONREPL - log error */
        return NULL;
    }

    replica_root = replica_get_root(r);

    if (prev) {
        obj = objset_next_obj(agmt_set, prev);
    } else {
        obj = objset_first_obj(agmt_set);
    }
    for (; obj; obj = objset_next_obj(agmt_set, obj)) {
        agmt = (Repl_Agmt *)object_get_data(obj);
        if (!agmt) {
            continue;
        }

        agmt_root = agmt_get_replarea(agmt);
        if (!agmt_root) {
            continue;
        }

        if (slapi_sdn_compare(replica_root, agmt_root) == 0) {
            slapi_sdn_free(&agmt_root);
            return obj;
        }

        slapi_sdn_free(&agmt_root);
    }

    return NULL;
}
