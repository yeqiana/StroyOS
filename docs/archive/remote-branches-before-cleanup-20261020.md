# StoryOS 远程分支退役归档 · 2026-10-20

> 注意：本分支通过合成 Git 多父提交保存退役分支历史，**不是功能合并，禁止合并进生产默认分支**。
> Commit ancestry contains the exact original tips of all branches below.

原远程分支数：107；开放 PR：0；受保护分支：0。
归档基线：fd1f55bc82ba6b5edf3fee225d601d350b5c01ea
归档规则：保留原始 Git 对象与 SHA，分支名称可按下表重建。

恢复范例：`git branch restore/example <下表对应的40位SHA>`，需要重新发布时再 `git push origin restore/example`。
本地同时有独立 `git bundle` 快照，且不删除本地工作区。

| 退役前分支 | 不可变提交 SHA |
| --- | --- |
| `codex/storyos-authorized-unknown-recovery` | `79e34512ee4797f8cc247ac78974161b11239425` |
| `codex/storyos-production-revision-epoch` | `6620dae395757abccf62093565ff32f8c0e66ad5` |
| `feat/image-context-20261020` | `3352a7594272c7016d6a3e05391d2532acd13bae` |
| `feature/rea-account-fidelity-four-20261014` | `9947e3a2bb04d1ca613afec6c076e9afdacd09b1` |
| `feature/rea-p1-ui-simplification-20261015` | `613438d2ac58ff1b9f70184b64ad9bab548c751a` |
| `feature/rea-settings-account-20261014` | `a23df73a303514a272a5e6a4190a5cd87d22a7d7` |
| `feature/storyos-five-mu-authority-handoff-20261009` | `6f9cd488a0f77ded6605ca56ea7778085be01e87` |
| `feature/storyos-fixed-create-entry-r27-20261016` | `a9866a2d6895f1d1c6b870768f05062ecd9643bc` |
| `feature/storyos-local-backfill-20261009` | `cf9566315327af0cfc67ad84b7834a972596dd01` |
| `feature/storyos-monitor-p2-clarity-20261015` | `a3070c74a25a22e3f638c0db52d079a717c3f1ef` |
| `feature/storyos-monitor-r25-stability-20261015` | `af4a17a24afd38915399fdade83dd167655c5577` |
| `feature/storyos-multi-episode-permanent-contract-20261010` | `4c4896cef4ba664fe817a5b720a20709a6fbf3e8` |
| `feature/storyos-multi-episode-production-20261009` | `716299400f14f6b5f0f8e3cb682364f12cde5370` |
| `feature/storyos-native-cas-resume-s4-20261010` | `bba7936b5c1abedb7006c190d19cea752e514113` |
| `feature/storyos-native-codex-full-auto-entry-20261010` | `2a4d889e678fe4913de83ab79ccdeae015e0ac2e` |
| `feature/storyos-performance-forensic-archive-20261009` | `fefeab6eb55902db014d219c0542945e5cc9a991` |
| `feature/storyos-r12-preserved-mainline-review-20261010` | `30cb76fdf13efb1f37f7b33bd4885df0428a1bf8` |
| `feature/storyos-r19-draft-handoff-plan-20261013` | `d4c33a84153a88376419cbe1aa6a77fce0b8bfa2` |
| `feature/storyos-r23-codex-shell-login-20261015` | `7887241b7324fc55da79965e21e8de9d88699326` |
| `feature/storyos-r28-advanced-nav-20261015` | `e35bde74df86331758c655247ca6cc146477d4fb` |
| `feature/storyos-redis-ui-r26-20261015` | `e6daddeca6ef42012728db727bef7e91d8fa6e95` |
| `feature/storyos-release-asset-audit-20261009` | `3a284479b59761a0de9c14b87daa6e22842ecd2b` |
| `feature/storyos-revision-migration-plan-20261010` | `14da38847c09c24da2440c2b306432f6beb170ce` |
| `feature/storyos-revision-schema-readonly-20261010` | `fb2467165ccdc819cc9cff075702a1f1d7240e49` |
| `feature/storyos-web-console-r28-20261016` | `df08f602cc54e3d51114f593b6f80b75df8fe754` |
| `feature/storyos-web-console-r29-20261016` | `7d4349c5cbf5403080f0ed9e464d1dc8a5f42457` |
| `feature/storyos-web-console-r30-20261016` | `0b335e6c78266129eab75c86e9f03291cee17f3f` |
| `feature/storyos-webconsole-mainline-integration-20261010` | `ff792bd507ca062b193d4c3742f3bd8a73839eca` |
| `fix/autonomy-final-20261017` | `01a29c194aa34e83f871a280a158495e08158200` |
| `fix/autonomy-regression-20261016` | `1b99cf9088576a66110e88b2bbdd087c8138353f` |
| `fix/autonomy-unknown-probe-20261019` | `e1e08cc4f14bb5d63eefbf056f7f6b9ba60750ee` |
| `fix/codex-cli-version-warning-before-banner-20261010` | `e7f144cee5455141b921b490865e313b78efaf40` |
| `fix/driver-nonzero-remediation-20261018` | `7d36aa360f8374c2c6c9d56777a4f6dad14e07b6` |
| `fix/final-semantic-fail-20261018` | `a8b88644c5a0fba54a16e9c6f2c82fd55560d157` |
| `fix/final-semantic-source-binding-20261018` | `e692a73936e183482356080352493634fb6e1214` |
| `fix/isolated-concept-critic-codex-home-20261010` | `7fe324d5108f31302f9c4edada90a910d0231e96` |
| `fix/locked-story-gates-20261008` | `9481e2886481ecf3d3e4428f3feee72bc5382bc7` |
| `fix/native-429-attempt-proof-20261019` | `3293508e08aaa4fd83f6526882d3ba14ad199668` |
| `fix/native-batch-followon-after-success-20261016` | `3adf4e2964008d5c6cca601c98bd40e373491603` |
| `fix/native-batch-next-action-priority-20261016` | `0f97c62c37a69421c0f07deaa4e2f34557a954de` |
| `fix/native-batch-proof-20261016` | `0f123e70c19779a831ba95fc47b4329e9b115b20` |
| `fix/native-capability-plan-20261016` | `9f3c7ece7996b7741b93b3cd92b2d355e3feb5f1` |
| `fix/native-codex-child-runtime-env-authority-20261010` | `64675228c34ddecb2cef6ff431f62c2999f0a5f9` |
| `fix/native-codex-model-readiness-20261010` | `f73d8d8023ff50010354d1769cc017e3e113741e` |
| `fix/native-driver-carrier-timeout-20261016` | `5bc48339d9978951348727370659b7694f0bc35f` |
| `fix/native-image-artifact-first-20261019` | `d838e567bfeaec2e5d3dec332670cccb2772ba5a` |
| `fix/native-image-attempt2-sha-raw-reconcile-20261017` | `81da945034660a9291709705be99a495a49ac44c` |
| `fix/native-image-outcome-proof-20261019` | `38404bdbe3feaee27e5598c0d61f2780e0bb771b` |
| `fix/native-image-unknown-audit-20261017` | `fbfa3b659ec25f88753b35e3a90680796a6e1a55` |
| `fix/native-network-second-attempt-tool-preflight-20261017` | `c135d4faf246dfa76261f346419d1480dd5646b2` |
| `fix/native-repair-capability-20261019` | `613cc84bea5804960e2be4a29d82022ecbde0e95` |
| `fix/native-runner-failed-lifecycle-request-identity-20261016` | `a32337f7cdb55a817b33f3f580153954cd0307d7` |
| `fix/native-runner-lifecycle-request-identity-20261016` | `462d2b14aad3501f8e01d1c72230a6232ba51352` |
| `fix/native-runner-live-cli-version-20261010` | `65985488c68a974c044d26ac3fc543caa431afcb` |
| `fix/native-runner-predispatch-classification-20261016` | `b52101e5055dcac07650bb8ad14b3a9f6255e0a7` |
| `fix/native-runner-stale-20261017` | `01f14fbb45eb5bbf724546ee053188b60a01868a` |
| `fix/native-unknown-preserved-raw-cas-20261016` | `83abb00bc2290c867a580e9e7c461c6fb1d30628` |
| `fix/native-verified-network-terminal-rearm-20261017` | `a1cab454d2157b22b8e6115a26d6235aba4aec3e` |
| `fix/one-wave-native-routing-20261019` | `a68fd3ce737ab5c89e2a0271fdaa6cdd4c0629ae` |
| `fix/prompt-source-projection-20261016` | `672043171810e76d67c0acbfcabb94eabfe0fa12` |
| `fix/recent5-verified-story-gate-projection-20261011` | `d1cb91ec60bf2c534dbfdc2553bc2f1c67d6cce6` |
| `fix/repair-wave-call-20261019` | `b49e6e4580f22e06057366e9f4d9ba21750adf1d` |
| `fix/reviewed-repair-rc4-recovery-20261019` | `7d5ccf6bd402cf7660bdc9695356f898956176b0` |
| `fix/second-review-weak-pass-policy-20261019` | `9f456576a1fa6d00887ae5e8f3f8c6149b1c9bf3` |
| `fix/story-photo-text-source-repair-epoch-20261010` | `a1bfee7d4e0594036575770d9ae59023e850cb61` |
| `fix/story-review-epoch7-8-authority-verifier-20261011` | `691a89faca18f737eedb3bec3fc898819bbd1073` |
| `fix/story-semantic-critic-isolated-home-20261010` | `edaae167648e0a7619b8ae53ba75bc1ab64eba84` |
| `fix/storyos-a8-verify-continuation-20261011` | `3f5632acb5d2e1338b0d73b217650023fd853dab` |
| `fix/storyos-codex-login-context-20261009` | `8451905d304ad2b00486524dad40df342ce09ad7` |
| `fix/storyos-creative-recovery-evidence-20261010` | `c94d0f6c102d1360839c3c83a48aa9749c9b7ea5` |
| `fix/storyos-episode-atomic-claim-20261010` | `a61161e65bf0b00f5a212d6077c2cbc81f8de1d1` |
| `fix/storyos-fallback-safe-20261010` | `13592ae5afbec26e1b7847687785a246e7cf148e` |
| `fix/storyos-native-baseline-runner-receipt-20261011` | `77176bf40c3760867b768310e41a50bea9196958` |
| `fix/storyos-native-model-proof-20261010` | `57efd37dcc2aba05fc4cfa34276625bdb65a6395` |
| `fix/storyos-native-preimage-character-frozen-20261011` | `731eceafa8c68097382aab3c6cbfb0787afc52d5` |
| `fix/storyos-native-preimage-host-envelope-20261011` | `65bab70a0dc53fed9436b10ae66ff721e7c05ac0` |
| `fix/storyos-native-runner-single-image-fence-20261011` | `ad9919fdf939be8de4d17ab0a1b495b2dede253a` |
| `fix/storyos-native-unknown-cas-r2-chatgpt-20261011` | `48b5b6ca00e2fc138fa612c816a8d09a995cb670` |
| `fix/storyos-native-visual-baseline-probe-r1-20261011` | `906fff874141381d3d4a3bf34879975aef881f26` |
| `fix/storyos-no-reuse-retired-episode-id-20261010` | `96ed0ddcddf12f2f7b4d2c2d84f3e1db55ce68d7` |
| `fix/storyos-r12-native-critic-epoch-20261013` | `4f7730bc862c5e475156fd98ac6fb801d61e947c` |
| `fix/storyos-r13-review-integration-20261013` | `39bf319f223bedad01553dba63316db4da7ed65e` |
| `fix/storyos-revision-baseline-fence-20261010` | `325faa8698033c59a24e6a8bd3023a1bc5ee7d21` |
| `fix/storyos-story-character-revision-20261011` | `06b0a2ff428371f7ea045c47ee49028922078e8c` |
| `fix/storyos-visual-lock-readonly-blocker-20261011` | `2751cbc6bd5d290fb8c24bb93ad02fe34dd498b8` |
| `fix/storyos-windows-capacity-diagnostics-20261010` | `b8cf1fab753a64a2b5358d1f26957154d1b09b01` |
| `fix/windows-image-lock-init-race-20261010` | `4e7beb19071d830ecacf8a73f72bed9d20068cd3` |
| `integration/story-platform-batches-20261009` | `b34d38063c0d1264462a3e345301456fde5cc4ef` |
| `integration/story-platform-next-batches-20261009` | `2de881f1ddf9467bb9d05f95d3c06d450fc19a56` |
| `integration/storyos-character-review-lock-20261010` | `3b96e322f7be808bfbf6614f35e09fcbaed7cbcf` |
| `integration/storyos-locked-gates-20261009` | `0727b8919e4f4fae080a0ee194056fac7d175201` |
| `integration/storyos-phase5a-recovery-candidate-20261009` | `9d74a9b9a2e29df4e8ddfa27d48bbd6f62faa636` |
| `integration/storyos-r18-20261011` | `cf18df5bbcfdaaded2ffe66783819c70784a17e9` |
| `integration/storyos-r19-20261011` | `826edefb1d22dbe4003878cbec0fd87069844ca2` |
| `integration/storyos-r19-on-remote-main-20261011` | `dc04dcf0a9957da920e5c8840310beb655dd84e8` |
| `integration/storyos-r20-clean-main-20261011` | `01b88d680bf9a41bbe7bc0063e6d922a592597dd` |
| `integration/storyos-r21-r22-clean-main-20261011` | `ee7b92b8164fc259ec7ddbb92a57d6f9bc4fb540` |
| `integration/storyos-r23-r24-on-remote-20261011` | `62c76d505bed60fd5dc7bd3ad9e89d8f703e776a` |
| `integration/storyos-revision-multi-episode-20261009` | `58ea09ccdf097ced737e66d583dd45ea749c5be3` |
| `integration/storyos-ui-r13-r16-20261011` | `d6f0d7134d1aa17b0ca557c44ded44089dd330f2` |
| `integration/storyos-ui-r17-20261011` | `e70cc9243ff8d87591f2511353ded2c8eafaa53f` |
| `integration/storyos-webconsole-real-merge-20261010` | `a9cbd81b0fe35f655823a35a3d6d65f77dd375a3` |
| `main` | `1d37cd0a9e81b5a1a4c37d9d2f3e289ff03127da` |
| `story` | `7ca675d6446c030ac6017b59cf1bbfc5ca0aeb30` |
| `story-platform-v3-rever` | `fd1f55bc82ba6b5edf3fee225d601d350b5c01ea` |
| `storyos-main-integration-20261009` | `4bd816c64a69dc1bd211849f4978ee02f3a8dbc4` |
| `storyos-scheduler-authority-plan-20261009` | `773f4096d93b33c265e9c91401fa53aae80318f7` |

这份清单仅用于历史恢复，不表示任何分支已通过正式质量验收。
