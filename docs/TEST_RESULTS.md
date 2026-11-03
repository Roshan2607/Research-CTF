# Test results

Run on 2026-11-04 (Windows 11, Python 3.12.10; networkx 3.4.2, pandas 2.2.3, streamlit 1.50.0, reportlab 4.4.1, PyMuPDF 2.1; pdftotext 4.00 present).

```
python -m pytest -v
```

**98 passed, 0 failed, 0 skipped.**

| Area | File | Tests |
|---|---|---|
| graph_schema | tests/test_graph_schema.py | 9 |
| graph_validation | tests/test_graph_validation.py | 11 |
| path_discovery | tests/test_path_discovery.py | 11 |
| participant_isolation | tests/test_participant_isolation.py | 13 |
| prompt_injection | tests/test_prompt_injection.py | 11 |
| scoring | tests/test_scoring.py | 20 |
| flag_validation | tests/test_flag_validation.py | 14 |
| kaggle | tests/test_kaggle.py | 6 |
| apps | tests/test_apps.py | 3 |

Additional checks (not unit tests):

- `python scripts/verify_evidence.py`: 42 quoted evidence passages found in their open-access sources, 0 missing, 6 official web pages skipped (checked manually).
- `python scripts/build_challenge.py`: graph valid, answer key consistent, 473-edge universe with 41 reference edges.
- Live servers: both apps return `ok` on `/_stcore/health`; HTTP requests for `data/answer_key/final_answer.json`, `data/organiser/master_graph.json` and `.env` return only the Streamlit app shell.

<details><summary>Full test list</summary>

```
tests/test_apps.py::test_participant_app_full_flow PASSED
tests/test_apps.py::test_backend_returns_aggregate_only PASSED
tests/test_apps.py::test_organiser_app_requires_password_and_runs PASSED
tests/test_flag_validation.py::test_normalisation_is_consistent PASSED
tests/test_flag_validation.py::test_correct_answer_accepted PASSED
tests/test_flag_validation.py::test_incorrect_answers_rejected PASSED
tests/test_flag_validation.py::test_alternative_application_goes_to_manual_review PASSED
tests/test_flag_validation.py::test_accepted_alternative_after_review PASSED
tests/test_flag_validation.py::test_product_name_alone_is_not_enough PASSED
tests/test_flag_validation.py::test_one_shot_and_no_early_feedback PASSED
tests/test_flag_validation.py::test_deadline_blocks_submission PASSED
tests/test_flag_validation.py::test_flags_are_team_bound PASSED
tests/test_flag_validation.py::test_registry_contains_no_plaintext_answers PASSED
tests/test_flag_validation.py::test_tokens_depend_on_secret PASSED
tests/test_flag_validation.py::test_wrong_secret_detected PASSED
tests/test_flag_validation.py::test_missing_secret_detected PASSED
tests/test_flag_validation.py::test_secret_never_exposed_to_client_files PASSED
tests/test_graph_schema.py::test_vocabulary_contains_required_relations PASSED
tests/test_graph_schema.py::test_every_relation_has_direction_and_meaning PASSED
tests/test_graph_schema.py::test_claim_kinds_distinguish_citation_from_method_and_concept PASSED
tests/test_graph_schema.py::test_all_node_types_in_master_graph_are_valid PASSED
tests/test_graph_schema.py::test_all_relationship_types_in_master_graph_are_valid PASSED
tests/test_graph_schema.py::test_corpus_size_and_domains PASSED
tests/test_graph_schema.py::test_symmetric_canonicalisation PASSED
tests/test_graph_schema.py::test_edge_direction_preserved_in_built_graph PASSED
tests/test_graph_schema.py::test_participant_dictionary_only_contains_submittable_paper_relations PASSED
tests/test_graph_validation.py::test_master_graph_is_valid PASSED
tests/test_graph_validation.py::test_every_edge_has_provenance PASSED
tests/test_graph_validation.py::test_papers_have_required_metadata PASSED
tests/test_graph_validation.py::test_duplicate_edges_detected PASSED
tests/test_graph_validation.py::test_invalid_relationship_type_rejected PASSED
tests/test_graph_validation.py::test_invalid_signature_rejected PASSED
tests/test_graph_validation.py::test_temporally_impossible_direction_rejected PASSED
tests/test_graph_validation.py::test_missing_evidence_rejected PASSED
tests/test_graph_validation.py::test_ai_proposed_edge_cannot_be_verified_without_human PASSED
tests/test_graph_validation.py::test_promotion_requires_named_reviewer_and_evidence PASSED
tests/test_graph_validation.py::test_hidden_connection_not_in_master_graph PASSED
tests/test_kaggle.py::test_kaggle_metric_matches_local_scorer[initial] PASSED
tests/test_kaggle.py::test_kaggle_metric_matches_local_scorer[revised] PASSED
tests/test_kaggle.py::test_public_candidate_file_matches_solution_ids PASSED
tests/test_kaggle.py::test_public_kaggle_files_leak_nothing PASSED
tests/test_kaggle.py::test_roundtrip_conversion PASSED
tests/test_kaggle.py::test_metric_rejects_bad_submissions PASSED
tests/test_participant_isolation.py::test_participant_files_exist PASSED
tests/test_participant_isolation.py::test_no_organiser_role_labels PASSED
tests/test_participant_isolation.py::test_no_internal_ids_or_concept_nodes PASSED
tests/test_participant_isolation.py::test_target_and_application_not_identified PASSED
tests/test_participant_isolation.py::test_cards_are_uniform PASSED
tests/test_participant_isolation.py::test_no_organiser_annotations_leak PASSED
tests/test_participant_isolation.py::test_abstracts_match_source_manifest PASSED
tests/test_participant_isolation.py::test_participant_ids_are_not_role_ordered PASSED
tests/test_participant_isolation.py::test_participant_loader_refuses_protected_paths PASSED
tests/test_participant_isolation.py::test_answer_key_not_under_participant_dir PASSED
tests/test_participant_isolation.py::test_participant_view_never_touches_answer_key_directly PASSED
tests/test_participant_isolation.py::test_participant_app_entrypoint_is_separate_from_organiser PASSED
tests/test_participant_isolation.py::test_vocabulary_examples_are_outside_corpus PASSED
tests/test_path_discovery.py::test_canonical_path_exists_in_organiser_graph PASSED
tests/test_path_discovery.py::test_canonical_path_retrievable_by_stage1 PASSED
tests/test_path_discovery.py::test_alternative_paths_independently_represented PASSED
tests/test_path_discovery.py::test_hidden_connection_not_traversable PASSED
tests/test_path_discovery.py::test_stage1_only_uses_verified_edges PASSED
tests/test_path_discovery.py::test_relevance_pruning_removes_off_topic_papers PASSED
tests/test_path_discovery.py::test_stage2_produces_diverse_routes PASSED
tests/test_path_discovery.py::test_stage3_rediscovers_hidden_principle_but_does_not_verify_it PASSED
tests/test_path_discovery.py::test_stage3_marks_existing_relation_verified PASSED
tests/test_path_discovery.py::test_stage4_requires_defensible_relation PASSED
tests/test_path_discovery.py::test_full_pipeline_runs PASSED
tests/test_prompt_injection.py::test_annotations_are_distinguishable_in_organiser_metadata PASSED
tests/test_prompt_injection.py::test_injections_hosted_on_non_role_cards PASSED
tests/test_prompt_injection.py::test_pymupdf_extracts_injection_only_from_host PASSED
tests/test_prompt_injection.py::test_pdftotext_extracts_injection PASSED
tests/test_prompt_injection.py::test_injection_is_rendered_invisibly PASSED
tests/test_prompt_injection.py::test_document_pipeline_flags_injected_instructions PASSED
tests/test_prompt_injection.py::test_original_abstract_unaltered_on_every_card PASSED
tests/test_prompt_injection.py::test_cards_have_identical_layout PASSED
tests/test_prompt_injection.py::test_document_instructions_are_never_privileged PASSED
tests/test_prompt_injection.py::test_naive_assistant_is_manipulated_and_guard_quarantines PASSED
tests/test_prompt_injection.py::test_injected_edges_carry_heaviest_penalty PASSED
tests/test_scoring.py::test_formula_matches_specification PASSED
tests/test_scoring.py::test_zero_denominators_are_safe PASSED
tests/test_scoring.py::test_perfect_submission_scores_one PASSED
tests/test_scoring.py::test_correct_edges_increase_score PASSED
tests/test_scoring.py::test_missing_edges_reduce_recall_not_precision PASSED
tests/test_scoring.py::test_unsupported_edges_reduce_precision PASSED
tests/test_scoring.py::test_wrong_relationship_type_is_penalised PASSED
tests/test_scoring.py::test_decoy_and_injection_weights_applied PASSED
tests/test_scoring.py::test_injection_edges_are_the_annotated_ones PASSED
tests/test_scoring.py::test_hidden_pair_is_neutral_for_every_type PASSED
tests/test_scoring.py::test_neutral_edges_do_not_change_score PASSED
tests/test_scoring.py::test_accepted_alternative_becomes_reference PASSED
tests/test_scoring.py::test_scores_stay_in_range PASSED
tests/test_scoring.py::test_participant_view_is_aggregate_only PASSED
tests/test_scoring.py::test_empty_submission_does_not_crash PASSED
tests/test_scoring.py::test_duplicates_are_counted_once PASSED
tests/test_scoring.py::test_unknown_ids_and_types_rejected PASSED
tests/test_scoring.py::test_invalid_direction_rejected PASSED
tests/test_scoring.py::test_malformed_submissions_rejected PASSED
tests/test_scoring.py::test_evidence_reference_is_optional_and_kept PASSED
```

</details>
