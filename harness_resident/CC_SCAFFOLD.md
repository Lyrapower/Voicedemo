# Claude Code Scaffold

Each CC job gets:

```text
agent_jobs/J-xxxx/
  TASK.md
  CONTEXT.json
  RESULT.md
```

`CONTEXT.json` carries only operational capability boundaries:

```json
{
  "job_id":"J-...",
  "allowed_tools":["read","test","edit"],
  "allowed_paths":["gateway/"],
  "approval_mode":"write_ok_no_deploy"
}
```

Claude Code is an executor, not a memory owner or router.

For stronger enforcement, wire your existing CC hook/guard into this job directory and validate `allowed_paths` before writes.
