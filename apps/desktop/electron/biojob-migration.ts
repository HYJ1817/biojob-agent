import { randomUUID } from 'node:crypto'
import fs from 'node:fs'
import path from 'node:path'

export type BioJobMigrationStatus = 'migrated' | 'no-source' | 'target-exists'

export interface BioJobMigrationResult {
  status: BioJobMigrationStatus
  source: string
  target: string
}

export interface BioJobMigrationOptions {
  legacyHome: string
  targetHome: string
  copyDirectory?: (source: string, destination: string) => void
}

function defaultCopyDirectory(source: string, destination: string) {
  fs.cpSync(source, destination, {
    recursive: true,
    errorOnExist: true,
    force: false,
    preserveTimestamps: true
  })
}

function directoryManifest(root: string) {
  const entries = new Map<string, string>()

  function visit(directory: string, relativeDirectory: string) {
    for (const entry of fs.readdirSync(directory, { withFileTypes: true })) {
      const absolute = path.join(directory, entry.name)
      const relative = path.join(relativeDirectory, entry.name)
      const stat = fs.lstatSync(absolute)
      const kind = entry.isDirectory() ? 'directory' : entry.isSymbolicLink() ? 'symlink' : 'file'
      entries.set(relative, `${kind}:${stat.size}`)

      if (entry.isDirectory()) {
        visit(absolute, relative)
      }
    }
  }

  visit(root, '')

  return entries
}

function verifyCopy(source: string, destination: string) {
  const sourceManifest = directoryManifest(source)
  const destinationManifest = directoryManifest(destination)

  if (sourceManifest.size !== destinationManifest.size) {
    throw new Error('BioJob data migration verification failed: entry count differs')
  }

  for (const [relative, signature] of sourceManifest) {
    if (destinationManifest.get(relative) !== signature) {
      throw new Error(`BioJob data migration verification failed: ${relative}`)
    }
  }
}

export function migrateLegacyBioJobData(options: BioJobMigrationOptions): BioJobMigrationResult {
  const source = path.join(options.legacyHome, 'biojob')
  const target = path.join(options.targetHome, 'biojob')

  if (!fs.existsSync(source)) {
    return { status: 'no-source', source, target }
  }

  if (fs.existsSync(target)) {
    return { status: 'target-exists', source, target }
  }

  fs.mkdirSync(options.targetHome, { recursive: true })
  const temporary = path.join(options.targetHome, `.biojob-migrating-${process.pid}-${randomUUID()}`)
  const copyDirectory = options.copyDirectory || defaultCopyDirectory

  try {
    copyDirectory(source, temporary)
    verifyCopy(source, temporary)
    fs.renameSync(temporary, target)
  } catch (error) {
    fs.rmSync(temporary, { recursive: true, force: true })
    throw error
  }

  return { status: 'migrated', source, target }
}

