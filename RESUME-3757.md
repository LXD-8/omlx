# RESUME — PR jundot/omlx#3757, branch `feat/responses-complete-envelope`

Scratch note. It lives ONLY on `wip/responses-tool-declarations` (fork remote
`fork` = https://github.com/LXD-8/omlx.git). Never commit it to the PR branch.

## State at time of writing (3rd checkpoint — task COMPLETE)

- Tree: CLEAN on `feat/responses-complete-envelope` at commit `ee58c6d8`
  (implementation commit, pushed). Only untracked file is this note.
- PR branch `feat/responses-complete-envelope` pushed to `fork` at
  **ee58c6d846ec06cc767641f45a4e962ba6c6b88f**; PR #3757 headRefOid confirmed
  ee58c6d8. Title and body updated (current-state-only; new declaration policy).
- Suites GREEN (**526 passed**); SDK + Codex re-verification DONE (below).
- Nothing is half-applied; nothing remains except any follow-up the owner asks
  for. If a cold session resumes, re-read the PR and this note; there is no
  pending work item.

## What this task is (policy decision)

Codex CLI 0.154.0-alpha.6.2 unconditionally declares the hosted `web_search`
tool (`/Applications/ChatGPT.app/Contents/Resources/codex`). The old contract
returned 400 for any unsupported/hosted tool declaration, so real Codex
sessions could not run at all — and Codex is the consumer this endpoint was
built for.

NEW POLICY: separate *declaring* a capability from *using* it.

1. A tool declaration oMLX cannot expose is ACCEPTED, not rejected. It is not
   exposed to the model. Accepting an unused declaration provably does not
   change semantics.
2. The degradation is VISIBLE: the accepted-but-not-exposed tool types are
   reported in the `Warning` response header (same RFC 7234 `199 omlx "..."`
   mechanism the structured-output path uses). Streaming carries it too (SSE
   headers), so nothing is silent.
3. Never fabricate execution. Hosted tools are NOT mapped onto function tools.
4. KEEP rejecting input *item* types that replay a hosted round trip oMLX never
   performed (`web_search_call`, `file_search_call`, `computer_call*`,
   `code_interpreter_call`, `image_generation_call`, `mcp_call`,
   `mcp_list_tools`, `mcp_approval_*`, `custom_tool_call(_output)`,
   `item_reference`), and malformed declarations (function without `name`,
   namespace member that is not a tool object). Those remain 400.
5. `local_shell` and `custom` are in the declaration bucket: now
   accepted-but-not-exposed (Codex 0.154 does not actually send `local_shell`).

## Files touched (current state)

- `omlx/api/responses_utils.py`
  - Replaced `_DEGRADED_TOOL_TYPES`/`_UNSUPPORTED_TOOL_TYPES` with
    `_REDUNDANT_TOOL_TYPES = {"tool_search"}` (still a silent no-op: eager
    exposure already provides the capability) and `_HOSTED_TOOL_TYPES`
    (documentation of known hosted types; informs the warning label).
  - Removed `_unsupported_tool_error`; added `_warning_label_token` and
    `_unexposed_tool_label` (header-safe labels, e.g. `web_search (hosted)`,
    `foo (unknown type)`, `namespace (nested) in namespace mcp__demo__`).
  - `convert_responses_tools(..., unexposed=None)` gained an out-param: a list
    the function appends labels to. `_register_flat_tool` /
    `_register_namespace_tool` take the same list; unsupported/unknown/nested
    declarations are dropped and labelled instead of raising. Input-item
    rejection at ~line 478 is UNCHANGED (still 400).
  - `validate_responses_request` docstring updated; its field-level 400s are
    unchanged.
- `omlx/server.py`
  - Added `_unexposed_tools_warning_header(unexposed_tools: list[str])` near
    `_response_format_warning_header` (~line 4861).
  - `create_response`: builds `unexposed_tools` and `tools_warning`, sets
    `sse_headers["Warning"]` on the stream branch, and passes
    `headers={"Warning": tools_warning}` to `_json_response_or_keepalive` on
    the non-streaming branch. Import `Sequence` was deliberately NOT added
    (use `list[str]`).
- `tests/test_responses.py`
  - `test_unsupported_tool_types_are_rejected_by_name` ->
    `test_unsupported_tool_types_are_accepted_but_not_exposed` (asserts label).
  - `test_supported_and_unsupported_tools_mixed_still_rejects` ->
    `..._keeps_supported`.
  - `test_namespace_with_hosted_member_is_rejected` ->
    `..._dropped_and_reported`; `test_nested_namespace_is_rejected` ->
    `..._dropped_and_reported`.
  - `test_request_from_codex_like_json` now asserts local_shell is reported,
    not 400.
  - Added `test_unexposed_label_cannot_inject_a_header`.
- `tests/integration/test_e2e_streaming.py`
  - `test_responses_unsupported_tools_fail_loudly` ->
    `test_responses_unsupported_tool_declarations_are_accepted_with_warning`
    (parametrized stream False/True; asserts 200 + `Warning` names the tool).
  - Added `test_responses_codex_tool_list_with_web_search_succeeds` (functions
    + namespace + web_search -> 200, function call still emitted, warning
    names web_search).
  - `test_responses_unsupported_input_items_fail_loudly` UNCHANGED (still 400).

## Verified GREEN

```
cd /tmp/omlx-probe/omlx && PYTHONPATH=/Applications/oMLX.app/Contents/Resources/Python/framework-mlx-base/lib/python3.11/site-packages:$PWD /Users/li/.local/bin/uv run --no-project --python 3.11 --with pytest --with pytest-asyncio --with jinja2 python -m pytest <paths> -q -m ""
```

The `-m ""` is REQUIRED or pytest.ini deselects the integration tests.

- `tests/test_responses.py tests/test_server.py tests/integration/test_e2e_streaming.py tests/integration/test_server_endpoints.py tests/integration/test_responses_tool_merge.py -m ""` -> **526 passed** (commit ee58c6d8).
- Not run: the full default suite (14000+ tests); not required by the task.

## Re-verification results (DONE, 2nd checkpoint)

Throwaway server on `127.0.0.1:8011`, isolated `--base-path /tmp/omlx-8011-base`,
model `mlx-community--Llama-3.2-1B-Instruct-4bit` only (deliberately did NOT
load the user's big models in a second instance to avoid memory contention).
The user's server on :8000 was never touched. Server stopped afterwards.

- OpenAI Python SDK **3.16.2**: `responses.with_raw_response.create` with
  `web_search` + a function tool -> HTTP 200 and Warning header naming
  `web_search (hosted)`; `responses.stream` -> 200, same Warning,
  `response.completed` seen; hosted input item `web_search_call` -> 400;
  `local_shell` declaration -> 200 + Warning.
- `@ai-sdk/open-responses` **2.0.49** with **ai 7.0.107**: `generateText` and
  `streamText`, request body carrying `["function","web_search"]` (injected via
  the provider's `fetch` middleware because the provider has no public hosted-
  tool API) -> HTTP 200 and the same Warning on both paths.
- Codex CLI **0.154.0-alpha.6.2**: throwaway `CODEX_HOME`
  `/tmp/omlx-codex-direct`, custom `model_provider` `wire_api="responses"`,
  base_url directly `http://127.0.0.1:8011/v1` (NO proxy). `codex exec`
  completed with **exit 0** and returned text. A pass-through logging proxy
  (no body modification; `/tmp/omlx-verify/pass_through_proxy.py`) confirmed the
  declared tools were `["function"×8, "namespace", "web_search"]` and the
  upstream response was `200` with the Warning naming `web_search (hosted)`.
  Codex 0.154 does **not** send `local_shell`.
  LIMITATION: a *function-tool execution* round trip through Codex was not
  achieved here because the 1B model emitted `<|python_tag|>exec_command(...)`
  as text instead of a `function_call` item; the previous revision verified
  that round trip with the big Qwen model through the (stripping) proxy. What
  is verified here is that the web_search declaration no longer fails the
  session.

## Remaining steps (numbered)

1. ~~Full relevant suites~~ DONE (526 passed).
2. ~~OpenAI SDK / AI SDK `web_search` re-verification~~ DONE (above).
3. ~~Codex CLI round trip without the stripping proxy~~ DONE (above; see
   limitation).
4. Update PR #3757 title/description: current-state-only, no dev history; What
   changed / Limitations must reflect the new declaration policy (accepted-but-
   not-exposed list; hosted execution never faked; input items still rejected;
   note the contract reversal vs the earlier revision and why).
5. Push the PR branch `feat/responses-complete-envelope` to `fork` with an
   explicit lease; report the new head sha.
6. Final report: file:line changes, per-type behaviour, warning mechanism,
   verbatim test output, Codex/SDK outcome, new head sha, uncertainties.

## Environment / commands

- `gh` at `/Users/li/Library/Application Support/CherryStudio/Toolchain/mise/shims/gh`
  (add that dir to PATH; account LXD-8, has signing-key + repo scopes).
- Commits: signed with `git commit -S` (ssh signing, key
  `/Users/li/.ssh/id_ed25519_signing`), NO signoff.
- Push WIP (scratch):
  ```
  sha=$(git ls-remote fork wip/responses-tool-declarations | cut -f1)
  git push fork wip/responses-tool-declarations --force-with-lease=wip/responses-tool-declarations:$sha
  ```
- Push PR branch (only when green):
  ```
  sha=$(git ls-remote fork feat/responses-complete-envelope | cut -f1)
  git push fork feat/responses-complete-envelope --force-with-lease=feat/responses-complete-envelope:$sha
  ```
  (If the remote sha is empty, omit `--force-with-lease` for the first push.)
- PR: https://github.com/jundot/omlx/pull/3757 (head b5f8005c → add a new
  signed commit on top; do NOT rewrite b5f8005c/e54eab2e).

## Gotchas

- Do NOT relax `_UNSUPPORTED_INPUT_ITEM_TYPES`.
- `tool_search` stays a silent no-op (no Warning): its capability is fully
  subsumed by eager namespace expansion, so warning would imply a lost
  capability that was not lost.
- Unknown tool types are accepted-but-not-exposed too (uniform rule; warns as
  `(unknown type)`). This was a judgement call — mention in the PR.
- Header labels are sanitised in `_warning_label_token` (RFC-token-safe chars,
  80-char cap) to prevent header injection from a client-supplied `type`.
- ruff: file style uses `List`/`Dict`/`Optional`; the repo has ~182 pre-existing
  UP006/UP045 findings under a current ruff, so do not rewrite imports.
