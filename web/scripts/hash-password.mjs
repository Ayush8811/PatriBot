#!/usr/bin/env node
/**
 * Print a PATRIBOT_AUTH_PASSWORD_HASH line for the web app's single owner account.
 *
 *   npm run hash-password                 # prompts twice, input hidden
 *   printf '%s' "$PW" | npm run hash-password --silent
 *   npm run hash-password -- 'my password'   # works, but the password lands in your shell history
 *
 * Output format: scrypt$N$r$p$saltB64$hashB64 (must match lib/auth/password.ts; a unit test checks it).
 * stdout gets only the hash line; hints (incl. the \$-escaped form for .env files) go to stderr.
 */
import { randomBytes, scryptSync } from "node:crypto";

const N = 32768;
const r = 8;
const p = 1;
const KEY_LEN = 32;
const SALT_LEN = 16;
const MIN_LENGTH = 12;

function hash(password) {
  const salt = randomBytes(SALT_LEN);
  const key = scryptSync(password.normalize("NFKC"), salt, KEY_LEN, { N, r, p, maxmem: 256 * N * r + 1024 * 1024 });
  return ["scrypt", N, r, p, salt.toString("base64"), key.toString("base64")].join("$");
}

/** Read one line from a TTY without echoing it. */
function promptHidden(question) {
  return new Promise((resolve, reject) => {
    const { stdin, stderr } = process;
    stderr.write(question);
    stdin.setRawMode(true);
    stdin.resume();
    stdin.setEncoding("utf8");
    let value = "";
    const onData = (chunk) => {
      for (const ch of chunk) {
        if (ch === "\r" || ch === "\n" || ch === "\u0004") {
          stdin.setRawMode(false);
          stdin.pause();
          stdin.off("data", onData);
          stderr.write("\n");
          resolve(value);
          return;
        }
        if (ch === "\u0003") {
          stdin.setRawMode(false);
          stderr.write("\n");
          reject(new Error("cancelled"));
          return;
        }
        if (ch === "\u007f" || ch === "\b") value = value.slice(0, -1);
        else value += ch;
      }
    };
    stdin.on("data", onData);
  });
}

async function readPiped() {
  let data = "";
  process.stdin.setEncoding("utf8");
  for await (const chunk of process.stdin) data += chunk;
  return data.replace(/\r?\n$/, "");
}

async function main() {
  let password;
  if (process.argv[2] !== undefined) {
    password = process.argv[2];
  } else if (process.stdin.isTTY) {
    password = await promptHidden("Password: ");
    const again = await promptHidden("Repeat password: ");
    if (password !== again) throw new Error("passwords do not match");
  } else {
    password = await readPiped();
  }
  if (!password) throw new Error("empty password");
  if (password.length < MIN_LENGTH) {
    process.stderr.write(`warning: use at least ${MIN_LENGTH} characters (a long random passphrase is best)\n`);
  }
  const line = hash(password);
  process.stdout.write(`${line}\n`);
  // Next.js expands $VAR in .env files, so there every "$" must be escaped. Vercel's dashboard takes the line as is.
  process.stderr.write(
    `\nVercel: paste the line above as PATRIBOT_AUTH_PASSWORD_HASH.\n` +
      `.env.local: PATRIBOT_AUTH_PASSWORD_HASH=${line.replaceAll("$", "\\$")}\n`,
  );
}

main().catch((err) => {
  process.stderr.write(`hash-password: ${err.message}\n`);
  process.exit(1);
});
