import assert from 'node:assert/strict'
import { execFileSync } from 'node:child_process'
import { randomBytes } from 'node:crypto'
import { mkdtempSync, mkdirSync, rmSync, writeFileSync } from 'node:fs'
import os from 'node:os'
import path from 'node:path'

import { test } from 'vitest'

import { buildBioJobSource } from './build-biojob-source.mjs'

function makeRepository() {
  const root = mkdtempSync(path.join(os.tmpdir(), 'biojob-source-test-'))
  mkdirSync(path.join(root, 'apps', 'desktop'), { recursive: true })
  writeFileSync(path.join(root, 'pyproject.toml'), '[project]\nname = "biojob-test"\n')
  writeFileSync(path.join(root, 'apps', 'desktop', 'package.json'), '{"name":"biojob-test"}\n')
  writeFileSync(path.join(root, 'payload.bin'), randomBytes(180_000))
  execFileSync('git', ['init'], { cwd: root, stdio: 'ignore' })
  execFileSync('git', ['add', '-A'], { cwd: root, stdio: 'ignore' })
  execFileSync(
    'git',
    ['-c', 'user.name=BioJob Test', '-c', 'user.email=test@biojob.local', 'commit', '-m', 'fixture'],
    { cwd: root, stdio: 'ignore' }
  )
  return root
}

test('buildBioJobSource creates a non-empty archive from a clean commit', () => {
  const root = makeRepository()
  const output = path.join(root, 'out', 'biojob-agent-source.zip')

  try {
    const result = buildBioJobSource({ repoRoot: root, output })
    assert.equal(result.output, output)
    assert.ok(result.size >= 100_000)
    const listing = execFileSync('tar', ['-tf', output], { cwd: root, encoding: 'utf8' })
    assert.match(listing, /pyproject\.toml/)
  } finally {
    rmSync(root, { recursive: true, force: true })
  }
})

test('buildBioJobSource rejects tracked changes', () => {
  const root = makeRepository()

  try {
    writeFileSync(path.join(root, 'pyproject.toml'), '[project]\nname = "dirty"\n')
    assert.throws(() => buildBioJobSource({ repoRoot: root }), /tracked-dirty/)
  } finally {
    rmSync(root, { recursive: true, force: true })
  }
})
