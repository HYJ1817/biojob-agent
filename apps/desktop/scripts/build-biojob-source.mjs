/** Build the self-contained first-launch source payload for BioJob Agent. */

import { execFileSync } from 'node:child_process'
import { mkdirSync, rmSync, statSync } from 'node:fs'
import path from 'node:path'

import { isMain } from './utils.mjs'

const DESKTOP_ROOT = path.resolve(import.meta.dirname, '..')
const REPO_ROOT = path.resolve(DESKTOP_ROOT, '..', '..')
const OUTPUT = path.join(DESKTOP_ROOT, 'build', 'biojob-agent-source.zip')

export function buildBioJobSource({ repoRoot = REPO_ROOT, output = OUTPUT } = {}) {
  const status = execFileSync('git', ['status', '--porcelain', '-uno'], {
    cwd: repoRoot,
    encoding: 'utf8',
    stdio: ['ignore', 'pipe', 'inherit']
  }).trim()

  if (status) {
    throw new Error('refusing to package BioJob source from a tracked-dirty working tree')
  }

  mkdirSync(path.dirname(output), { recursive: true })
  rmSync(output, { force: true })
  execFileSync('git', ['archive', '--format=zip', `--output=${output}`, 'HEAD'], {
    cwd: repoRoot,
    stdio: 'inherit'
  })

  const size = statSync(output).size

  if (size < 100_000) {
    throw new Error(`BioJob source payload is unexpectedly small (${size} bytes)`)
  }

  return { output, size }
}

if (isMain(import.meta.url)) {
  const result = buildBioJobSource()
  console.log(`[build-biojob-source] wrote ${result.output} (${result.size} bytes)`)
}
