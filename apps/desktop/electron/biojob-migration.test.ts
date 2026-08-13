import assert from 'node:assert/strict'
import fs from 'node:fs'
import os from 'node:os'
import path from 'node:path'

import { test } from 'vitest'

import { migrateLegacyBioJobData } from './biojob-migration'

function withTempRoot(run: (root: string) => void) {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), 'biojob-migration-'))

  try {
    run(root)
  } finally {
    fs.rmSync(root, { recursive: true, force: true })
  }
}

test('migration copies only BioJob data and preserves the legacy source', () =>
  withTempRoot(root => {
    const legacyHome = path.join(root, 'legacy-hermes')
    const targetHome = path.join(root, 'BioJob Agent')
    fs.mkdirSync(path.join(legacyHome, 'biojob', 'exports'), { recursive: true })
    fs.writeFileSync(path.join(legacyHome, 'biojob', 'biojob.sqlite3'), 'db')
    fs.writeFileSync(path.join(legacyHome, 'biojob', 'exports', 'applications.xlsx'), 'sheet')
    fs.writeFileSync(path.join(legacyHome, 'config.yaml'), 'model: secret')
    fs.writeFileSync(path.join(legacyHome, '.env'), 'API_KEY=secret')

    const result = migrateLegacyBioJobData({ legacyHome, targetHome })

    assert.equal(result.status, 'migrated')
    assert.equal(fs.readFileSync(path.join(targetHome, 'biojob', 'biojob.sqlite3'), 'utf8'), 'db')
    assert.equal(fs.readFileSync(path.join(targetHome, 'biojob', 'exports', 'applications.xlsx'), 'utf8'), 'sheet')
    assert.equal(fs.existsSync(path.join(targetHome, 'config.yaml')), false)
    assert.equal(fs.existsSync(path.join(targetHome, '.env')), false)
    assert.equal(fs.readFileSync(path.join(legacyHome, 'biojob', 'biojob.sqlite3'), 'utf8'), 'db')
  }))

test('migration is a no-op when the legacy BioJob directory is absent', () =>
  withTempRoot(root => {
    const result = migrateLegacyBioJobData({
      legacyHome: path.join(root, 'legacy-hermes'),
      targetHome: path.join(root, 'BioJob Agent')
    })

    assert.equal(result.status, 'no-source')
  }))

test('migration never overwrites an existing BioJob directory', () =>
  withTempRoot(root => {
    const legacyHome = path.join(root, 'legacy-hermes')
    const targetHome = path.join(root, 'BioJob Agent')
    fs.mkdirSync(path.join(legacyHome, 'biojob'), { recursive: true })
    fs.mkdirSync(path.join(targetHome, 'biojob'), { recursive: true })
    fs.writeFileSync(path.join(legacyHome, 'biojob', 'biojob.sqlite3'), 'old')
    fs.writeFileSync(path.join(targetHome, 'biojob', 'biojob.sqlite3'), 'new')

    const result = migrateLegacyBioJobData({ legacyHome, targetHome })

    assert.equal(result.status, 'target-exists')
    assert.equal(fs.readFileSync(path.join(targetHome, 'biojob', 'biojob.sqlite3'), 'utf8'), 'new')
  }))

test('failed migration removes its partial copy and leaves the source untouched', () =>
  withTempRoot(root => {
    const legacyHome = path.join(root, 'legacy-hermes')
    const targetHome = path.join(root, 'BioJob Agent')
    fs.mkdirSync(path.join(legacyHome, 'biojob'), { recursive: true })
    fs.writeFileSync(path.join(legacyHome, 'biojob', 'biojob.sqlite3'), 'db')

    assert.throws(
      () =>
        migrateLegacyBioJobData({
          legacyHome,
          targetHome,
          copyDirectory: (_source, destination) => {
            fs.mkdirSync(destination, { recursive: true })
            fs.writeFileSync(path.join(destination, 'partial'), 'partial')
            throw new Error('copy failed')
          }
        }),
      /copy failed/
    )

    assert.equal(fs.existsSync(path.join(targetHome, 'biojob')), false)
    assert.deepEqual(
      fs.existsSync(targetHome)
        ? fs.readdirSync(targetHome).filter(name => name.startsWith('.biojob-migrating-'))
        : [],
      []
    )
    assert.equal(fs.readFileSync(path.join(legacyHome, 'biojob', 'biojob.sqlite3'), 'utf8'), 'db')
  }))

