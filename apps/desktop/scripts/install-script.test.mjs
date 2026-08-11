import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import path from 'node:path'

import { test } from 'vitest'

const installer = readFileSync(path.resolve(import.meta.dirname, '..', '..', '..', 'scripts', 'install.ps1'), 'utf8')

test('bundled repository git commands tolerate non-error stderr and check exit codes', () => {
  const start = installer.indexOf('if ($LocalArchive) {')
  const end = installer.indexOf('# Try SSH first', start)
  const localArchiveBlock = installer.slice(start, end)

  assert.ok(start >= 0 && end > start, 'local archive install block must exist')
  assert.doesNotMatch(localArchiveBlock, /^\s+git\s/m, 'native git commands must use the relaxed-error wrapper')
  assert.ok(
    (localArchiveBlock.match(/Invoke-NativeWithRelaxedErrorAction \{ git /g) ?? []).length >= 5,
    'every bundled repository git step must use the relaxed-error wrapper'
  )
  assert.ok(
    (localArchiveBlock.match(/\$LASTEXITCODE -ne 0/g) ?? []).length >= 5,
    'every bundled repository git step must check its real exit code'
  )
})
