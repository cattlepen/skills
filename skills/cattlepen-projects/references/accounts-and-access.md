# Accounts, rights and project access

Every MCP call acts as the signed-in user, inside one account. Projects, tasks, library entries
and runner keys belong to an account, so a call aimed at the wrong account finds nothing or
creates in the wrong place.

## Where a call lands

`whoami` returns `user_id`, `account_id` (the active account), `role`, `permissions`,
`seat_count`, `plan_status`, `plan_valid_until`, `self_hosted` and `is_installation_admin`.

`list_accounts` returns `items[{account_id, name, type, role, seat_count, plan_status}]`. On
Cattlepen cloud a user can have a personal account and organisation accounts. A self-hosted
installation has one organisation (`type: "organization"`), and `list_accounts` shows only it.

Most tools take an optional `account_id`. Omitted, the call goes to the server's default account:
the personal account on Cattlepen cloud, the organisation on a self-hosted installation. `whoami`
names the account a call without `account_id` lands in. When the user names an account, find its `account_id` in
`list_accounts` and pass it on every call of the job, reads included, so that ids from one call
are looked up in the same account by the next.

## Rights

`permissions` in `whoami` decides what you can do. The ones this skill needs:

| Permission | Allows |
| --- | --- |
| `manage_projects` | Creating, changing and deleting projects; the account's exhaust queue setting. |
| `start_run` | Queueing, dequeueing and starting runs. |
| `issue_own_key` | Creating runner keys owned by you. |

An ordinary member of a self-hosted organisation was measured with `issue_own_key`, `start_run`
and `view_account` only: such a user can work on tasks of projects they were granted, but cannot
create a project. If a write is refused for rights, tell the user who can do it instead of
looking for another route.

## Project access on a self-hosted installation

Observed on a self-hosted installation:

- The user who creates a project becomes its first explicit member.
- A member sees only the projects granted to them: before a grant, a second user's
  `list_projects` was empty and `get_project` answered 404; after it, the project was listed.
- Installation admins can see and administer every project, but queueing still needs explicit
  membership, admins included: 403 "queueing requires explicit project membership".
- A runner key counts for a project's tasks only when its owner is a member of the project.
  A teammate's shared runner does nothing for a project they are not a member of.

Managing members needs an installation admin (`is_installation_admin: true`); a member's read of
the member list is refused with 403 "installation admin required". Calls, all through the generic
API tools:

| Goal | Tool and operation |
| --- | --- |
| Find a user's id | `read_api_operation{operation: "GET /self-host/admin/users", request: {query: {q: "<name or email>"}}}` returns `items[].user_id` |
| List a project's members | `read_api_operation{operation: "GET /projects/{id}/members", request: {path: {id}}}` returns `{count, items[{user_id, granted_by, granted_at}]}` |
| Grant access | `mutate_api_operation{operation: "PUT /projects/{id}/members/{user_id}", request: {path: {id, user_id}}}` returns 204 |
| Remove access | `mutate_api_operation{operation: "DELETE /projects/{id}/members/{user_id}", request: {path: {id, user_id}}}` returns 204 |

Granting or removing access changes what another person can see and run: do it only when the
user asks for that person by name. Removing the person who queued a task makes that task wait
with `queue_wait: "project_access_revoked"`.

A project invite link is `POST /projects/{id}/invites` with an optional `ttl_hours` (default 168);
it returns a single-use `token` shown once. Treat the token like a password: give it to the user,
do not repeat it.

## Account members on Cattlepen cloud

`list_members{account_id}` lists an account's members (`user_id`, `role`, `joined_at`).
`set_member_role`, `remove_member` (both for owners only), `create_invite`, `list_invites` and
`revoke_invite` manage an organisation's members on Cattlepen cloud; an invite's token is shown
once. Use them only on an explicit request.
