# infra/privileged/

The complete list of root privilege the deploy account holds on the VPS, the scripts that
privilege points at, and the argument for the shape.

> **Nothing here has been installed on a host.** No VPS exists
> (`docs/evidence/raghava-deploy-teardown.md` §9.1 items 1 and 9: a Hostinger VPS, and root
> on it, are both external blockers). `visudo -c` has not been run against the policy in an
> environment with sudo. Read §5 before believing any of it works.

---

## 1. The finding this answers

`docs/evidence/raghava-deploy-teardown.md` §8.3 read the reference host's documented
sudoers grants (`CLIENT_VPS_SETUP_GUIDE.md:1238-1268`):

```
<runner-user> ALL=(root) NOPASSWD: /usr/bin/rm -rf /var/lib/docker/containers/*
<runner-user> ALL=(root) NOPASSWD: /usr/bin/cp /tmp/*.nginx.conf /etc/nginx/sites-available/*.conf
<runner-user> ALL=(root) NOPASSWD: /usr/bin/cp /tmp/tmp.* /etc/nginx/sites-available/*.conf
<runner-user> ALL=(root) NOPASSWD: /usr/bin/systemctl restart docker
```

**sudo matches command-line arguments as one concatenated string, and a wildcard in that
string matches `/` and spans words.** The canonical illustration in the sudo documentation
is that a rule permitting `cat /var/log/*` also permits `cat /var/log/messages /etc/shadow`.
So line 1 permits `sudo rm -rf /var/lib/docker/containers/x /etc /home` — unrestricted root
deletion of any path on the box — held by the account that runs code from every merged pull
request. Line 3 was *widened* to `/tmp/tmp.*` to accommodate `mktemp`, with a note in their
hardening history that it is "still scoped to a specific dest"; the traversal defeats that,
and `/tmp` is world-writable, so any local user can stage the source file.

Sources (accessed 17 Aug 2026):
[sudoers(5)](https://www.man7.org/linux/man-pages/man5/sudoers.5.html) ·
[Compass Security — Dangerous Sudoers Entries, Part 4: Wildcards](https://blog.compass-security.com/2012/10/dangerous-sudoers-entries-part-4-wildcards/) ·
[David Hamann — Beware of wildcard paths in sudo commands (24 Feb 2023)](https://davidhamann.de/2023/02/24/beware-of-wildcard-paths-sudo/)

## 2. What is here, and where each file installs

```
infra/privileged/sudoers.d/calevate-deploy      -> /etc/sudoers.d/calevate-deploy   root:root 0440
infra/privileged/sbin/calevate-nginx-apply      -> /usr/local/sbin/calevate-nginx-apply  root:root 0755
```

```sh
sudo install -o root -g root -m 0755 infra/privileged/sbin/calevate-nginx-apply /usr/local/sbin/
sudo install -o root -g root -m 0440 infra/privileged/sudoers.d/calevate-deploy /etc/sudoers.d/
sudo visudo -c -f /etc/sudoers.d/calevate-deploy        # must print "parsed OK"

# the staging directory the script reads, owned by the deploy account and nobody else
sudo install -d -o root     -g root     -m 0755 /var/lib/calevate
sudo install -d -o calevate -g calevate -m 0750 /var/lib/calevate/nginx-staging
sudo install -d -o calevate -g calevate -m 0750 /var/lib/calevate/nginx-staging/conf.d
sudo install -d -o calevate -g calevate -m 0750 /var/lib/calevate/nginx-staging/snippets
```

**The scripts must be root-owned and not writable by the deploy account**, or the grant is
equivalent to full root: a script the caller can rewrite is a command the caller can
construct. That is why they are installed to `/usr/local/sbin` by root rather than executed
out of `/var/www/calevate`, which the deploy account owns and rewrites on every deploy.

## 3. The shape, and the one rule

**One root-owned script per privileged action, granted by exact absolute path, with `""` as
the argument specification — which is sudoers for "may be run only with an empty argument
list".** The deploy account can NAME a privileged action; it can never COMPOSE one.

**No wildcard in any argument position, for any reason.** Not in this file, not in any
successor, not "just for `mktemp`". `tests/host_hygiene_test.py` fails the build on a `*`
or a `?` anywhere in a Cmnd line and on any Cmnd that does not end in `""`.

Everything that varies about an action travels through a fixed staging directory the root
script validates. `calevate-nginx-apply` refuses: a symlinked staging root, a staging root
owned by anyone but the deploy account, a world-writable staging root, a subdirectory, a
symlink, a non-regular file, and any basename outside `^[a-z0-9][a-z0-9._-]*\.conf$`. The
threat model it is written against is "the deploy account is compromised", in which the
staging directory is attacker-controlled input.

**What the grant does NOT hand over.** The deploy account already chooses the nginx
configuration — `infra/nginx/*.template` lives in the repository it deploys — so that is not
a privilege this creates. What the script refuses to hand over is everything else: writing
outside `/etc/nginx`, reading a file the deploy account cannot already read, deleting
anything it did not introduce in this run, and running a command of the account's
construction.

**The deploy user's name appears in exactly three places and they must agree:** the
`Defaults:` and Cmnd lines in `sudoers.d/calevate-deploy`, `DEPLOY_USER` in
`sbin/calevate-nginx-apply`, and the owner of `/var/lib/calevate/nginx-staging`. The script
verifies the third against the second at run time and refuses on a mismatch, so a
half-renamed account fails loudly instead of installing config staged by the wrong user.

## 4. What is deliberately NOT granted

| Not granted | Why |
|---|---|
| `rm` under `/var/lib/docker`, wildcard or not | Dead-container tombstones are DETECTED and refused with the exact command for a human (DEPLOYMENT §4 step 4). An automated `rm -rf` under the daemon's state directory is a bigger hazard than the fault it fixes, and holding the grant at all means the account can be made to use it. |
| `systemctl restart docker` | Not a deploy step. An incident action, taken by a human who has read `runbooks/deploy-failed.md`. |
| a bare `systemctl reload nginx` | Reachable only through the script, which reloads a configuration it has just tested. A bare reload grant lets a caller reload whatever is on disk — the failure the test exists to prevent. |
| anything for the daily hygiene job | `scripts/deploy/host-hygiene.sh` runs entirely unprivileged: Docker via the `docker` group, pm2 as its own owner, and the journal bounded declaratively by `infra/hygiene/journald-cap.conf` rather than vacuumed by a privileged daily command. A scheduled job holding root is a scheduled root shell. |
| `certbot` | Renewal runs from certbot's own timer as root with the reload attached as a deploy hook (DEPLOYMENT §9.5a step 5). The deploy account is not in that path. |
| a maintenance-page installer | The maintenance gate is a named gap (DEPLOYMENT §5), so there is no action to grant. When it is built it gets its own argument-free script and its own line, not a widened one. |

**`docker` group membership is root-equivalent and is not made worse by anything here.**
DEPLOYMENT §2 puts the deploy user in that group so the deploy can build and swap
containers, and a member of it can mount the host filesystem into a container. That is a
known, accepted property of running Docker deploys as a non-root account; the sudoers
policy neither adds to it nor is excused by it. What the policy is for is the actions that
are *not* Docker — and those are exactly one.

## 5. What a human must do before any of this is real

1. **Install both files** as §2 shows, and run `visudo -c -f` on the policy. *Pass
   condition*: "parsed OK". A syntax error in `/etc/sudoers.d/` can lock the host out of
   sudo entirely, so `visudo` is not optional and `cp` is not a substitute.
2. **Check the filename survived.** `sudo -l -U calevate` must list
   `/usr/local/sbin/calevate-nginx-apply`. If it lists nothing, the file is being ignored —
   sudo's `#includedir` silently skips any name containing a `.` or ending in `~`.
3. **Prove the argument refusal**: `sudo -n /usr/local/sbin/calevate-nginx-apply --help`
   must be refused by *sudo*, before the script runs. *Pass condition*: "Sorry, user
   calevate is not allowed to execute…".
4. **Prove the happy path once, attended**, with `NGINX_AUTO_RELOAD=1` and a rendered
   config already reviewed by hand (DEPLOYMENT §9.5a keeps `NGINX_AUTO_RELOAD` unset for the
   whole first pass, so this is step 5's successor, not part of it). *Pass condition*: the
   script prints the file count, `nginx -t` passes, nginx reloads, and the four hostnames
   still answer.
5. **Prove the restore path**, by staging a deliberately broken conf and running it. *Pass
   condition*: it refuses, `/etc/nginx` matches what it did before, and `nginx -t` passes
   afterwards. This is the property the whole backup dance exists for and it has never been
   exercised.
