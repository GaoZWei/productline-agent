#!/usr/bin/env sh
set -eu

rework_acceptance_root="$(CDPATH= cd -- "$(dirname "$0")/.." && pwd)"
rework_acceptance_case="tests/e2e/test_rework_acceptance.py::test_rework_acceptance_independent_fixture"
rework_acceptance_existing="tests/e2e/test_rework_acceptance.py::test_rework_acceptance_existing_database_is_preserved"
rework_acceptance_flows="tests/e2e/test_rework_acceptance_flows.py"
rework_acceptance_safety="tests/e2e/test_rework_acceptance_safety.py"
rework_acceptance_golden="tests/e2e/test_rework_acceptance_golden.py::test_rework_acceptance_golden_old_queries_and_fixed_diagnosis"
rework_acceptance_web="tests/e2e/test_rework_page.py::test_rework_page_reads_real_java_through_web_proxy"

run_rework_acceptance() {
  sh "${rework_acceptance_root}/scripts/test-rework-query-e2e.sh" "$@"
}

# 两次各自启动并清理独占Java/PostgreSQL；复用相同业务编号证明不依赖旧结果。
for rework_acceptance_run in 1 2; do
  printf 'M8.8隔离验收 %s/2\n' "${rework_acceptance_run}"
  if [ "${rework_acceptance_run}" -eq 1 ]; then
    run_rework_acceptance "${rework_acceptance_case}[PENDING]" \
      "${rework_acceptance_case}[CHECKED]" "${rework_acceptance_case}[INTERRUPTED]" \
      "${rework_acceptance_existing}" \
      "${rework_acceptance_flows}::test_rework_acceptance_normal_first_round" \
      "${rework_acceptance_flows}::test_rework_acceptance_changed_evidence_and_second_round[processing]" \
      "${rework_acceptance_flows}::test_rework_acceptance_changed_evidence_and_second_round[inspection]" \
      "${rework_acceptance_safety}::test_rework_acceptance_replay_and_final_version_race" \
      "${rework_acceptance_safety}::test_rework_acceptance_permissions_binding_and_lost_response" \
      "${rework_acceptance_safety}::test_rework_acceptance_receipt_failure_rolls_back_all_business_facts" \
      "${rework_acceptance_golden}" "${rework_acceptance_web}" "$@"
  else
    run_rework_acceptance "${rework_acceptance_web}" "${rework_acceptance_golden}" \
      "${rework_acceptance_safety}::test_rework_acceptance_receipt_failure_rolls_back_all_business_facts" \
      "${rework_acceptance_safety}::test_rework_acceptance_permissions_binding_and_lost_response" \
      "${rework_acceptance_safety}::test_rework_acceptance_replay_and_final_version_race" \
      "${rework_acceptance_flows}::test_rework_acceptance_changed_evidence_and_second_round[inspection]" \
      "${rework_acceptance_flows}::test_rework_acceptance_changed_evidence_and_second_round[processing]" \
      "${rework_acceptance_flows}::test_rework_acceptance_normal_first_round" \
      "${rework_acceptance_existing}" \
      "${rework_acceptance_case}[INTERRUPTED]" "${rework_acceptance_case}[CHECKED]" \
      "${rework_acceptance_case}[PENDING]" "$@"
  fi
done
