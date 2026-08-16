/**
 * The pm2 definition for the Next.js server, without which the deploy cannot start it.
 *
 * `scripts/vps-deploy.sh` ran `pm2 reload calevate-web`, which exits non-zero on an
 * unregistered app — and nothing in this repository ever ran `pm2 start`. There was no
 * ecosystem file, and `docs/DEPLOYMENT.md` §2 lists only `pm2 startup`, which makes pm2
 * resurrect a SAVED process list rather than create one. So a first deploy on a fresh host
 * aborted at the web step, with migrations already applied and all three containers
 * already swapped, and `runbooks/deploy-failed.md` then told the operator to start it
 * "from the ecosystem definition" — a file that did not exist.
 *
 * `.cjs`, not `.js`: pm2 loads this with `require()`, and `apps/web/package.json` is part
 * of an ESM-ish Next project. The explicit CommonJS extension is what stops Node reading
 * it as a module and failing on `module.exports`.
 *
 * WHY NOT A CONTAINER, like the other three services. DEPLOYMENT §1 settles it: `next
 * build` peaks over 2GB, and a container would add a second memory ceiling to a build that
 * already needs swap on this host class. So the web tier runs on the host under pm2, and
 * this file is the only place that fact is executable.
 */

module.exports = {
  apps: [
    {
      // The name `vps-deploy.sh` reloads and `runbooks/database-restore.md` starts. It is
      // the identifier, so it is not decorative — changing it here changes two runbooks.
      name: "calevate-web",
      // `pnpm` rather than `next` directly: the binary lives in the workspace's virtual
      // store, and resolving it by hand is how a path breaks on the next install.
      script: "pnpm",
      args: "start",
      cwd: __dirname,

      // ONE INSTANCE, deliberately. Next's own server is not the bottleneck here — the
      // API is — and cluster mode would multiply the RSS of a process that already holds
      // the built app in memory, on a host sized by DEPLOYMENT §2a for four voice-runtime
      // workers plus two api workers plus Postgres. Revisit only with a measurement.
      instances: 1,
      exec_mode: "fork",

      // The environment is inherited from the shell the deploy runs in, and every
      // NEXT_PUBLIC_* was already inlined at BUILD time from `apps/web/.env.local`
      // (see that file's `.env.example`). Nothing here supplies a secret: pm2's process
      // list is world-readable via `pm2 jlist`, so a value placed here would be a secret
      // in a place DEPLOYMENT §6 does not name.
      env: {
        NODE_ENV: "production",
        PORT: 3000,
      },

      // Restart policy. `max_restarts` with `min_uptime` is what distinguishes "crashed
      // once on a bad request" from "crashes on boot": ten failures inside ten seconds
      // each is a broken build, and pm2 should stop rather than spin.
      autorestart: true,
      min_uptime: "10s",
      max_restarts: 10,
      // A Next server that has grown past this is leaking; restarting is a mitigation and
      // not a fix, so the number is high enough that a healthy process never reaches it.
      max_memory_restart: "1G",

      // pm2 writes to ~/.pm2/logs by default; naming them keeps the two streams separable
      // when `runbooks/deploy-failed.md` §5 asks for the web build's output.
      out_file: "/var/log/calevate/web-out.log",
      error_file: "/var/log/calevate/web-error.log",
      merge_logs: true,
      time: true,
    },
  ],
};
