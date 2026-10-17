# CAMX reprojection recipes

One row per site project (`family/project` of `data/datasets.json`, 75) plus `genrobot/gripper_v4`, the on-disk key of four datasets the site folds into `genrobot/10kh`. `recipes.json` holds the same data in machine form; `reproject.py` reads it. Paths are relative to this folder. "Rerun route" = the site rendered the clip with the headless Rerun viewer; here it maps to the OpenCV multiview renderer with the same viz config.

The **site renderer** column says how the current site clip of each project was made (read off the `DONE.json` of the source render trees): `opencv` = the renderers shipped in `lib/`, which reproduce those clips almost pixel for pixel; `rerun` = the headless Rerun viewer (`lerobot_rerun_viz.py`), whose clips have the SAME geometry and placement (same poses, intrinsics, configs and gripper URDFs) but a lighter, smoothly per-face shaded look, about 20 grey levels brighter than the flat grey OpenCV draw of this release with its hard facets; `raw` = camera cuts without an overlay. Rerun is not part of this release; its clips are reproduced in geometry, not in shading.

Routes over the 75 site projects: agibot_beta 1, bimanual_fisheye 17, multiview 53, raw 4 (gripper_v4 is a second bimanual_fisheye entry).

Site renderer over the site projects: opencv 34, raw 4, rerun 37.

## Recipe table

| project | route | site renderer | config | lens (calib) | profile / stand-in | mode | notes |
|---|---|---|---|---|---|---|---|
| agibot/agibot_world_2026 | multiview | rerun | agibot_g2.json | episode K (all) | auto | urdf | the data_processing URDF copy (camera_optical link) is included under grippers/agibot_g2 |
| agibot/agibot_world_beta | agibot_beta | opencv | - | episode K (all) | ctag2f120_beta | cad | site tables |
| aloha/abc | multiview | rerun | abc_realsense.json (+rig rules) | episode K (all) | auto | urdf | site tables |
| aloha/aist_bimanip | multiview | rerun | aist_bimanip.json | config hfov | registry:aloha2 (override aloha2) | urdf | site tables |
| aloha/aloha_lerobot | multiview | rerun | aloha.json | config hfov | auto | urdf | site tables |
| aloha/aloha_lerobot_mobile | multiview | rerun | aloha.json | config hfov | auto | urdf | recovered from the source render log |
| aloha/biplay | multiview | rerun | biplay.json | config hfov | auto | urdf | site tables |
| aloha/cosmos_policy | multiview | rerun | aloha_cosmos_policy.json | config hfov | auto | urdf | site tables |
| aloha/galaxea | multiview | rerun | galaxea.json | config hfov | auto | urdf | site tables |
| aloha/molmoact_yam | multiview | rerun | molmoact2_yam.json | config hfov | auto | urdf | site tables |
| aloha/openneo_aloha | multiview | rerun | site/openneo_aloha_fx306.json / per-dataset | config hfov | registry:piper intac (stand-in piper intac); eef given | urdf | site tables |
| aloha/openneo_arx5 | multiview | opencv | openneo.json | main=openneo_wrist_d405_640x480_assumed.json:stretch | openneo | primitive | site tables |
| aloha/openneo_arx5_single | multiview | opencv | openneo_single.json | main=openneo_wrist_d405_640x480_assumed.json:stretch | openneo | primitive | site tables |
| aloha/rdt | multiview | rerun | rdt.json | config hfov | auto | urdf | site tables |
| aloha/robocoin | multiview | rerun | robocoin_cobot_magic.json (+rig rules) | config hfov | auto | urdf | site tables |
| aloha/robodojo | multiview | rerun | robodojo.json | config hfov | auto | urdf | site tables |
| aloha/robomind | multiview | rerun | robomind.json (+rig rules) | episode K (all) | registry:cobot magic v2 | urdf | site tables |
| aloha/xvla_softfold | multiview | rerun | xvla_softfold.json | config hfov | auto | urdf | site tables |
| dahuan/rh20t_cfg1 | multiview | rerun | rh20t.json | episode K (all) | auto | urdf | site tables |
| dahuan/rh20t_cfg2 | multiview | rerun | rh20t.json | episode K (all) | auto | urdf | site tables |
| daimon/dataclaw | bimanual_fisheye | opencv | - | per-device daimon_dataclaw_{device}.json, fallback main=daimon_dataclaw_fleet_fallback.json:stretch | dataclaw; eef given | primitive | candidate pose |
| dexumi/dexumi | raw | raw | - | - | - | raw | raw: inspire_*: the Inspire RH56 hand model and CAD are not publi... |
| dexwild/dexwild | raw | raw | - | - | - | raw | raw: the release publishes no camera intrinsics and no camera-to-... |
| fastumi/fastumi | bimanual_fisheye | opencv | - | main=gopro_hero9_maxlens_2_7k_umi.json:crop | fastumi | urdf | borrowed lens |
| fastumi/fastumi_100k_dual_arm | bimanual_fisheye | opencv | - | main=gopro_hero9_maxlens_2_7k_umi.json:crop | fastumi; own-only | urdf | site tables |
| fastumi/fastumi_100k_single_arm | bimanual_fisheye | opencv | - | main=gopro_hero9_maxlens_2_7k_umi.json:crop | fastumi | urdf | site tables |
| flexiv/openneo_flexiv | multiview | opencv | openneo_flexiv.json | main=openneo_wrist_d405_640x480_assumed.json:stretch | openneo; eef_tcp | primitive | site tables |
| franka_hand/fmb | multiview | rerun | fmb.json | config hfov | auto | urdf | site tables; tile height 256 |
| franka_hand/molmoact | multiview | rerun | molmoact.json | episode K (all) | auto | urdf | recovered from the source render log |
| franka_hand/rh20t_cfg5 | multiview | rerun | rh20t.json | episode K (all) | auto | urdf | site tables |
| freetacman/freetacman | multiview | opencv | freetacman.json | main=freetacman_camera3_equidistant.json:stretch | freetacman | primitive | recovered from the source render log |
| genrobot/10kh | bimanual_fisheye | opencv | - | per-episode genrobot_episodes/, fallback main=genrobot_das_camera0_session_mean.json:stretch | genrobot | urdf | site tables |
| genrobot/gripper_v4 | bimanual_fisheye | opencv | - | main=genrobot_das_camera0_sewing_mean.json:stretch | genrobot | urdf | site tables |
| hifi_umi/hifi_umi | multiview | opencv | - | all=hifi_umi_hand_fisheye.json:stretch | hifi_umi | primitive | site tables |
| iphumi/behavior_prompting | multiview | rerun | iphumi_bimanual.json | episode K (all) | auto | urdf | site tables |
| iphumi/gated_memory_policy | multiview | rerun | iphumi_right.json | episode K (all) | auto | urdf | site tables |
| iphumi/hommi | multiview | rerun | iphumi_bimanual.json | episode K (all) | auto | urdf | site tables |
| iphumi/mofpo | multiview | rerun | iphumi_bimanual_and_head.json | episode K (all) | auto | urdf | site tables |
| iphumi/muse | multiview | opencv | muse.json | episode K (all) | umift | urdf | recovered from the source render log |
| iphumi/umift | multiview | rerun | iphumi_left.json | episode K (all) | registry:umift | urdf | site tables |
| legato/legato | multiview | opencv | legato.json | config hfov | auto | urdf | recovered from the source render log; tile height 384 |
| manipforce/manipforce | raw | raw | - | - | - | raw | raw: no measured gripper width or calibrated camera translation i... |
| openarm/openarm | multiview | rerun | openarm_lerobot.json (+rig rules) | episode K (single-arm wrists only), else config hfov | auto | urdf | site tables |
| rby1/modpack | multiview | rerun | rby1_modpack.json (+rig rules) | episode K (all (+KB4 head)), else config hfov | auto | urdf | site tables |
| realman/realsource | multiview | rerun | realsource.json | episode K (all) | auto | urdf | site tables |
| robotiq/droid | multiview | rerun | droid.json | episode K (all) | auto | urdf | site tables |
| robotiq/droid_lowres | multiview | opencv | droid.json | config hfov + --hfov | auto | urdf | site tables |
| robotiq/rh20t_cfg4 | multiview | rerun | rh20t.json | episode K (all) | auto | urdf | site tables |
| robotiq/rh20t_cfg6 | multiview | rerun | rh20t.json | episode K (all) | auto | urdf | site tables |
| robotiq/rh20t_cfg7 | multiview | rerun | rh20t.json | episode K (all) | auto | urdf | site tables |
| robotiq/robomind_ur5 | multiview | opencv | robomind_ur5.json | episode K (third_* only), else config hfov | auto | urdf | site tables |
| robotiq/roboset_kinesthetic | multiview | rerun | roboset_kinesthetic.json | config hfov | auto | urdf | site tables |
| robotiq/roboset_teleop | multiview | rerun | roboset_teleop.json | config hfov | auto | urdf | site tables |
| stretch/dobbe | multiview | rerun | dobbe.json | config hfov | auto | urdf | site tables |
| umi/aetherock | multiview | opencv | - | main=aetherock_wrist_fisheye_assumed.json:stretch | primitive; eef given | primitive | candidate pose |
| umi/data_scaling_laws | bimanual_fisheye | opencv | - | main=gopro_hero9_maxlens_2_7k_umi.json:crop | umi | urdf | site tables |
| umi/exumi | bimanual_fisheye | opencv | - | main=gopro_hero9_maxlens_2_7k_umi.json:crop | exumi | urdf | site tables |
| umi/humi | bimanual_fisheye | opencv | - | main=gopro_hero9_maxlens_2_7k_humi_g1_masked.json:crop | umi | urdf | site tables |
| umi/maniwav | bimanual_fisheye | opencv | - | main=gopro_hero9_maxlens_2_7k_umi.json:crop | umi | urdf | site tables |
| umi/mvumi | bimanual_fisheye | opencv | - | main=gopro_hero9_maxlens_2_7k_umi.json:crop | umi | urdf | site tables |
| umi/openneo_umi | multiview | opencv | openneo_umi.json | main=openneo_wrist_d405_640x480_assumed.json:stretch | openneo; eef given; own-only | primitive | site tables |
| umi/openneo_umi_single | multiview | opencv | openneo_umi_single.json | main=openneo_wrist_d405_640x480_assumed.json:stretch | openneo; eef given | primitive | site tables |
| umi/tamen | multiview | opencv | tamen.json | config hfov | primitive; eef given | primitive | recovered from the source render log |
| umi/touch_in_the_wild | bimanual_fisheye | opencv | - | main=gopro_hero9_maxlens_2_7k_umi.json:crop | umi | urdf | site tables |
| umi/umi | bimanual_fisheye | opencv | - | main=gopro_hero9_maxlens_2_7k_umi.json:crop | umi | urdf | site tables |
| umi/umi3d | multiview | opencv | - | main=umi3d_fisheye_kb4_release_crop_masked.json:stretch | registry:umi3d | urdf | site tables |
| umi/umi_benchmark | bimanual_fisheye | opencv | - | main=umi_benchmark_fastumi_pro_seucm.json:crop | umi_benchmark | primitive | site tables |
| umi/umi_on_legs | bimanual_fisheye | opencv | - | main=gopro_hero9_maxlens_2_7k_umi.json:crop | umi | urdf | site tables |
| umi/vista_umi | bimanual_fisheye | opencv | - | main=umi_benchmark_fastumi_pro_seucm.json:crop | umi_benchmark; eef given; own-only | primitive | site tables |
| umi/vitamin | bimanual_fisheye | opencv | - | main=gopro_hero9_maxlens_2_7k_umi_gripper_masked.json:crop | umi | urdf | site tables |
| umi/vitamin_b | bimanual_fisheye | opencv | - | main=vitamin_b_gopro_webcam_224.json:crop | vitamin_b | urdf | site tables |
| ur/openneo_ur | multiview | opencv | openneo_ur.json | main=openneo_wrist_d405_640x480_assumed.json:stretch | openneo; eef_tcp | primitive | site tables |
| widowx/bridge_v2 | raw | raw | - | - | - | raw | raw: the wrist camera-to-flange transform is a prior, never fitte... |
| wsg50/rh20t_cfg3 | multiview | rerun | rh20t.json | episode K (all) | auto | urdf | site tables |
| xarm/mint_xarm | multiview | rerun | mint_xarm.json | config hfov | auto | urdf | recovered from the source render log |
| xhand/dexora | multiview | opencv | dexora.json | config hfov | axes | axes | site tables; fixed stride 3 |

Full provenance, line references and assumptions: the `note` field of each entry in `recipes.json`.

## Files each recipe references

Checked against this folder at generation time (`present` = the asset copy has it).

### Viz configs and lens files

| file | present | used by |
|---|---|---|
| calib/aetherock_wrist_fisheye_assumed.json | yes | umi/aetherock |
| calib/bridge_side2_20230708_candidate.json | yes | widowx/bridge_v2 |
| calib/daimon_dataclaw_fleet_fallback.json | yes | daimon/dataclaw |
| calib/daimon_dataclaw_{device}.json | yes | daimon/dataclaw |
| calib/freetacman_camera3_equidistant.json | yes | freetacman/freetacman |
| calib/genrobot_das_camera0_session_mean.json | yes | genrobot/10kh |
| calib/genrobot_das_camera0_sewing_mean.json | yes | genrobot/gripper_v4 |
| calib/genrobot_episodes/ | yes | genrobot/10kh |
| calib/gopro_hero9_maxlens_2_7k_humi_g1_masked.json | yes | umi/humi |
| calib/gopro_hero9_maxlens_2_7k_umi.json | yes | fastumi/fastumi, fastumi/fastumi_100k_dual_arm, fastumi/fastumi_100k_single_arm, umi/data_scaling_laws, umi/exumi, umi/maniwav, umi/mvumi, umi/touch_in_the_wild, umi/umi, umi/umi_on_legs |
| calib/gopro_hero9_maxlens_2_7k_umi_gripper_masked.json | yes | umi/vitamin |
| calib/hifi_umi_hand_fisheye.json | yes | hifi_umi/hifi_umi |
| calib/openneo_wrist_d405_640x480_assumed.json | yes | aloha/openneo_arx5, aloha/openneo_arx5_single, flexiv/openneo_flexiv, umi/openneo_umi, umi/openneo_umi_single, ur/openneo_ur |
| calib/umi3d_fisheye_kb4_release_crop_masked.json | yes | umi/umi3d |
| calib/umi_benchmark_fastumi_pro_seucm.json | yes | umi/umi_benchmark, umi/vista_umi |
| calib/vitamin_b_gopro_webcam_224.json | yes | umi/vitamin_b |
| config/abc_realsense.json | yes | aloha/abc |
| config/abc_zed.json | yes | aloha/abc |
| config/agibot_g2.json | yes | agibot/agibot_world_2026 |
| config/aist_bimanip.json | yes | aloha/aist_bimanip |
| config/aloha.json | yes | aloha/aloha_lerobot, aloha/aloha_lerobot_mobile |
| config/aloha_cosmos_policy.json | yes | aloha/cosmos_policy |
| config/biplay.json | yes | aloha/biplay |
| config/dexora.json | yes | xhand/dexora |
| config/dobbe.json | yes | stretch/dobbe |
| config/droid.json | yes | robotiq/droid, robotiq/droid_lowres |
| config/droid_autolab_failure_wrist_review_1016.json | yes | robotiq/droid |
| config/droid_pennpal_success_wrist_review_1016.json | yes | robotiq/droid |
| config/droid_weird_success_wrist_review_1016.json | yes | robotiq/droid |
| config/fmb.json | yes | franka_hand/fmb |
| config/freetacman.json | yes | freetacman/freetacman |
| config/galaxea.json | yes | aloha/galaxea |
| config/iphumi_bimanual.json | yes | iphumi/behavior_prompting, iphumi/hommi |
| config/iphumi_bimanual_and_head.json | yes | iphumi/mofpo |
| config/iphumi_left.json | yes | iphumi/umift |
| config/iphumi_right.json | yes | iphumi/gated_memory_policy |
| config/legato.json | yes | legato/legato |
| config/manipforce_battery_cad.json | yes | manipforce/manipforce |
| config/mint_xarm.json | yes | xarm/mint_xarm |
| config/molmoact.json | yes | franka_hand/molmoact |
| config/molmoact2_yam.json | yes | aloha/molmoact_yam |
| config/muse.json | yes | iphumi/muse |
| config/openarm_lerobot.json | yes | openarm/openarm |
| config/openarm_yuto.json | yes | openarm/openarm |
| config/openneo.json | yes | aloha/openneo_arx5 |
| config/openneo_flexiv.json | yes | flexiv/openneo_flexiv |
| config/openneo_single.json | yes | aloha/openneo_arx5_single |
| config/openneo_umi.json | yes | umi/openneo_umi |
| config/openneo_umi_single.json | yes | umi/openneo_umi_single |
| config/openneo_ur.json | yes | ur/openneo_ur |
| config/rby1_modpack.json | yes | rby1/modpack |
| config/rdt.json | yes | aloha/rdt |
| config/realsource.json | yes | realman/realsource |
| config/rh20t.json | yes | dahuan/rh20t_cfg1, dahuan/rh20t_cfg2, franka_hand/rh20t_cfg5, robotiq/rh20t_cfg4, robotiq/rh20t_cfg6, robotiq/rh20t_cfg7, wsg50/rh20t_cfg3 |
| config/robocoin_cobot_magic.json | yes | aloha/robocoin |
| config/robocoin_galaxea_r1_stereo.json | yes | aloha/robocoin |
| config/robodojo.json | yes | aloha/robodojo |
| config/robomind.json | yes | aloha/robomind |
| config/robomind_ur5.json | yes | robotiq/robomind_ur5 |
| config/roboset_kinesthetic.json | yes | robotiq/roboset_kinesthetic |
| config/roboset_teleop.json | yes | robotiq/roboset_teleop |
| config/site/aloha_openneo_aloha/ | yes | aloha/openneo_aloha |
| config/site/openneo_aloha_fx306.json | yes | aloha/openneo_aloha |
| config/tamen.json | yes | umi/tamen |
| config/xvla_softfold.json | yes | aloha/xvla_softfold |

### Gripper trees (grippers/<dir>, via gripper_registry.lookup of the models in datasets.json plus overrides / stand-ins / renderer kinds)

| grippers/ dir | present | used by |
|---|---|---|
| grippers/DAS_Gripper_V4/ | yes | genrobot/10kh, genrobot/gripper_v4 |
| grippers/agibot_g2/ | yes (has camera_optical) | agibot/agibot_world_2026 |
| grippers/aloha1/ | yes | aloha/aloha_lerobot, aloha/aloha_lerobot_mobile |
| grippers/aloha2/ | yes | aloha/aist_bimanip, aloha/biplay, aloha/cosmos_policy |
| grippers/arx_x5/ | yes | aloha/robodojo |
| grippers/cobot_magic/ | yes | aloha/rdt, aloha/robomind |
| grippers/crank_4310/ | yes | aloha/abc |
| grippers/ctag2f120_beta/ | yes | agibot/agibot_world_beta |
| grippers/ctag2f90d/ | yes | realman/realsource |
| grippers/dh_ag95/ | yes | dahuan/rh20t_cfg1, dahuan/rh20t_cfg2 |
| grippers/dobbe_stick/ | yes | stretch/dobbe |
| grippers/exumi/ | yes | umi/exumi |
| grippers/flexible_4310/ | yes | aloha/abc |
| grippers/franka_hand/ | yes | franka_hand/fmb, franka_hand/molmoact, franka_hand/rh20t_cfg5 |
| grippers/galaxea_r1lite/ | yes | aloha/galaxea, aloha/robocoin |
| grippers/legato/ | yes | legato/legato |
| grippers/linear_4310/ | yes | aloha/abc, aloha/molmoact_yam |
| grippers/manipforce/ | yes | manipforce/manipforce |
| grippers/openarm/ | yes | openarm/openarm |
| grippers/piper/ | yes | aloha/xvla_softfold |
| grippers/piper_intac/ | yes | aloha/openneo_aloha |
| grippers/piper_x/ | yes | aloha/robodojo |
| grippers/rby1_finray/ | yes | rby1/modpack |
| grippers/robomind/ | yes | aloha/robocoin, aloha/robomind |
| grippers/robotiq/ | yes | robotiq/droid, robotiq/droid_lowres, robotiq/rh20t_cfg4, robotiq/rh20t_cfg6, robotiq/rh20t_cfg7, robotiq/robomind_ur5, robotiq/roboset_kinesthetic, robotiq/roboset_teleop |
| grippers/umi/ | yes | fastumi/fastumi, fastumi/fastumi_100k_dual_arm, fastumi/fastumi_100k_single_arm, iphumi/behavior_prompting, iphumi/gated_memory_policy, iphumi/hommi, iphumi/mofpo, umi/data_scaling_laws, umi/humi, umi/maniwav, umi/mvumi, umi/touch_in_the_wild, umi/umi, umi/umi_on_legs, umi/vitamin |
| grippers/umi3d/ | yes | umi/umi3d |
| grippers/umift/ | yes | iphumi/muse, iphumi/umift |
| grippers/vitamin_b/ | yes | umi/vitamin_b |
| grippers/widowx250s/ | yes | widowx/bridge_v2 |
| grippers/wsg50/ | yes | wsg50/rh20t_cfg3 |
| grippers/xarm_gripper/ | yes | xarm/mint_xarm |
| grippers/xhand/ | yes | dexumi/dexumi |

Registry profiles / renderer kinds per project: agibot/agibot_world_2026: agibot_g2; agibot/agibot_world_beta: ctag2f120_beta; aloha/abc: yam, yam_crank_4310, yam_linear_4310; aloha/aist_bimanip: aloha2; aloha/aloha_lerobot: aloha1; aloha/aloha_lerobot_mobile: aloha1; aloha/biplay: aloha2; aloha/cosmos_policy: aloha2; aloha/galaxea: galaxea_r1lite; aloha/molmoact_yam: yam_linear_4310; aloha/openneo_aloha: piper intac; aloha/openneo_arx5: openneo (no URDF); aloha/openneo_arx5_single: openneo (no URDF); aloha/rdt: cobot_magic; aloha/robocoin: cobot_magic_v2, galaxea_r1lite; aloha/robodojo: arx_x5, piper_x; aloha/robomind: cobot_magic, cobot_magic_v2; aloha/xvla_softfold: piper; dahuan/rh20t_cfg1: dh_ag95; dahuan/rh20t_cfg2: dh_ag95; daimon/dataclaw: dataclaw (no URDF); dexumi/dexumi: 'inspire_rh56': no registry entry -> primitive, xhand; dexwild/dexwild: 'leap_hand_v2': no registry entry -> primitive; fastumi/fastumi: fastumi; fastumi/fastumi_100k_dual_arm: fastumi; fastumi/fastumi_100k_single_arm: fastumi; flexiv/openneo_flexiv: openneo (no URDF); franka_hand/fmb: franka_hand; franka_hand/molmoact: franka_hand_pantor; franka_hand/rh20t_cfg5: franka_hand; freetacman/freetacman: freetacman (no URDF); genrobot/10kh: genrobot; genrobot/gripper_v4: genrobot; hifi_umi/hifi_umi: hifi_umi (no URDF); iphumi/behavior_prompting: iphumi; iphumi/gated_memory_policy: iphumi; iphumi/hommi: iphumi; iphumi/mofpo: iphumi; iphumi/muse: umift; iphumi/umift: umift; legato/legato: legato; manipforce/manipforce: manipforce; openarm/openarm: openarm, openarm umi; rby1/modpack: rby1; realman/realsource: ctag2f90d; robotiq/droid: robotiq_2f85; robotiq/droid_lowres: robotiq_2f85; robotiq/rh20t_cfg4: robotiq_2f85; robotiq/rh20t_cfg6: robotiq_2f85; robotiq/rh20t_cfg7: robotiq_2f85; robotiq/robomind_ur5: robotiq_2f85; robotiq/roboset_kinesthetic: robotiq_2f85; robotiq/roboset_teleop: robotiq_2f85; stretch/dobbe: dobbe_stick; umi/aetherock: primitive (no URDF); umi/data_scaling_laws: umi; umi/exumi: exumi; umi/humi: umi; umi/maniwav: umi; umi/mvumi: umi; umi/openneo_umi: openneo (no URDF); umi/openneo_umi_single: openneo (no URDF); umi/tamen: primitive (no URDF); umi/touch_in_the_wild: umi; umi/umi: umi; umi/umi3d: umi3d; umi/umi_benchmark: umi_benchmark (no URDF); umi/umi_on_legs: umi; umi/vista_umi: umi_benchmark (no URDF); umi/vitamin: umi; umi/vitamin_b: vitamin_b; ur/openneo_ur: openneo (no URDF); widowx/bridge_v2: widowx250s, widowx250s_dense; wsg50/rh20t_cfg3: wsg50; xarm/mint_xarm: xarm_gripper; xhand/dexora: axes (no URDF).

Other inputs: `lib/white_overlay.py` + `lib/white_multiview.py` for the site look; `grippers/ctag2f120_beta/{calibration.json,meshes.npz}` for agibot_beta; the DataClaw per-device files `calib/daimon_dataclaw_dag911262r{000153,00025a,00054f,000646}.json`; `calib/genrobot_episodes/` holds only {clean_bowl,drawer_to_place_items,drawer_to_take_items,fold_and_store_shopping_bag}_ep0_{left,right}.json.

## What the release cannot reproduce exactly

- **Session-specific OpenNeo poses** (`aloha/openneo_aloha`): the three per-dataset configs in `config/site/aloha_openneo_aloha/` carry `static_pose_xyz_wxyz` (the fitted head pose) and `retarget_camera_in_eef` (the fitted wrist mount). The multiview renderer applies both using the same transforms as the Rerun viewer; those three fits do not calibrate other datasets or recording sessions.
- **Site look of the OpenCV routes**: the site clips drew every mesh in the Rerun grey through `tools/white_overlay.py` / `white_multiview.py` (ambient 0.58, `--alpha 1.0`; `reproject.py --look white`); `xhand/dexora` kept the colour look at `--alpha 0.9`.
- **Rerun-rendered site clips** (37 projects, `site renderer` = rerun above, incl. `rby1/modpack`): same inputs, configs and URDFs, but the headless Rerun viewer shades meshes smoothly and lighter than the flat grey OpenCV draw here, so those clips match in geometry, not pixel for pixel. `rby1/modpack` in addition: Rerun drew the head pair as plain pinhole while the multiview tool applies the KB4 coefficients of info.json, so its head tiles differ.
- **AgiBot G2**: the registry anchors at the URDF link `camera_optical`; `grippers/agibot_g2` in this folder is the `camx/data_processing/agibot/assets` copy that carries that link (checked at generation time: see the gripper table above).
- **Assumed / borrowed lenses**: GoPro Hero 9/10 Max-Lens calibration for every UMI-family rig incl. `fastumi/*` (no fisheye flag in the FastUMI v1 export) and `umi/vitamin_b` (webcam-mode crop chain assumed); assumed D405 / fx-306 pinhole files for the OpenNeoData wrists (also for the fisheye `openneo_umi*` streams); hfov priors in the configs of openneo (70), dexora (70), mint_xarm (56.1/60), molmoact (70), fmb (72.6/57.7), bridge; AetheRock 190-deg circle read as equidistant; nominal T265 (legato) and HBVCAM (freetacman, tamen) equidistant models; GenRobot session / sewing means where no per-episode camera_info file exists.
- **Candidate / prior poses**: DataClaw tool centre (converter-notes candidate), AetheRock tool centre (picked on video), Vista-UMI (UMI-Benchmark eef constant for both hands), DexUMI/DexWild (raw: no calibrated projection), robomind_ur5 static cameras and right base (priors), dexora (frames only). Bridge has a guarded own-wrist image-fit candidate with a corrected width map; its exported world camera motion remains invalid and is not used for this projection. ManipForce battery episode 0 has a guarded CAD/image fit; the second camera and other recordings remain raw. Its fitted optical centre preserves TCP but changes the legacy training camera motion.
- **Corrected / repaired data the site used instead of the release tree** (episode 0 clips the public samples cannot reproduce): `umi/umi_on_legs/tossing` (reviewed width derivative), `robotiq/droid_lowres/TRI_success` (reviewed exterior calibration transfer), `robotiq/droid_lowres/AUTOLab_success` and `IPRL_success` (reviewed round2/droid_anchors derivative with a per-episode eef; the sample carries the dataset median). `widowx/bridge_v2` is NOT such a case: the sample is the same side2 export the site read, only the episode differs (site ep6, sample ep0).
- **Legacy sample pose corrections**: the three audited episode-0 samples of `flexiv/openneo_flexiv` restore the session wrist mount from export openneo_4e8e8ac7_20260928; the three `franka_hand/rh20t_cfg5` samples apply the FK-verified 103.4 mm / 135 deg TCP-to-mount correction. Each repair matches dataset, episode and the shipped pose; corrected or unknown poses are preserved. These are render-only overrides, logged in meta.json; downloaded data and camera trajectories are unchanged. Other legacy episodes require corrected input metadata.
- **Recipes recovered from the source render logs** (no site table covers them; the exact site commands exist in the render trees and are encoded here): `umi/tamen` (fitted eef constants, excluded visuals), `freetacman/freetacman` (multiview route), `iphumi/muse` (bimanual kind umift), `legato/legato` (tile height 384; the site also decoded the frames at 3x before drawing, which no recipe key expresses), `aloha/aloha_lerobot_mobile` and `xarm/mint_xarm` (Rerun with config/aloha.json / config/mint_xarm.json), `franka_hand/molmoact` (Rerun; no OpenCV command on disk, per-episode intrinsics drive both tools).
- **Site tile size and stride**: `franka_hand/fmb` tiles are the native 256 px (`tile_height: 256`), `legato/legato` 384; `xhand/dexora` used a fixed stride 3 on 20 fps data (`stride: 3`). `genrobot/gripper_v4` passed `--cross off` for its two single-arm clips, which changes nothing because the bimanual renderer forces cross off for single-arm data. `aloha/robomind` fixes one gripper profile per dataset where the site switched per episode variant.
- **Per-rig profile rules** (`aloha/robomind`): the 12 Cobot Magic v1 datasets need `registry:cobot magic v1`; `config_by_rig` rules carry a `profile` key for them, which `reproject.py` applies together with the rule's config (verified on `fold_clothes` -> `--profile registry:cobot magic v1`).
- **Per-episode lens files** exist only for the GenRobot 10Kh site picks; other 10Kh episodes fall back to the session mean (fx 299.5 vs the per-episode 300/277).
- **Four-view cap**: the site shows at most 4 tiles (RH20T wrist + third_0..2, mofpo 4 of 6, robomind_ur5 4 of 6, dexwild up to 5 raw); `views` lists the site order.
