import type { Player, Position } from './types'

export const positionOrder: Position[] = ['GK', 'DEF', 'MID', 'FWD']

export function groupByPosition(players: Player[]): Record<Position, Player[]> {
  return {
    GK: players.filter((player) => player.position === 'GK'),
    DEF: players.filter((player) => player.position === 'DEF'),
    MID: players.filter((player) => player.position === 'MID'),
    FWD: players.filter((player) => player.position === 'FWD'),
  }
}

const palettes: Record<string, [string, string, string]> = {
  ARS: ['#a51f2d', '#efe8d9', '#172a46'],
  AVL: ['#6f2844', '#8dc1d6', '#f1e5d5'],
  BOU: ['#a82b31', '#202421', '#eee9dc'],
  BRE: ['#b72f35', '#f2eee3', '#202421'],
  BHA: ['#2f5fa9', '#ece9dd', '#e0b849'],
  EVE: ['#31568f', '#ebe8dc', '#202421'],
  LEE: ['#ebe9df', '#31518c', '#d1ad43'],
  LIV: ['#9f2631', '#eee8da', '#d6aa4d'],
  MCI: ['#75a8bf', '#eeeadd', '#342f3a'],
  MUN: ['#a82a31', '#eee9de', '#202421'],
  NFO: ['#a82c32', '#eee7d8', '#202421'],
  TOT: ['#eeeae0', '#1e3151', '#a7a9a4'],
}

export function teamPalette(team: string): [string, string, string] {
  return palettes[team] ?? ['#49695a', '#ece8dd', '#1f2923']
}

export function shortPlayerName(name: string): string {
  if (name.length <= 15) return name
  const parts = name.split(' ')
  if (parts.length > 1) return `${parts[0]?.[0]}. ${parts.at(-1)}`
  return `${name.slice(0, 13)}…`
}

export function formatPercent(value: number): string {
  return `${(value * 100).toFixed(0)}%`
}

export function formatObservedAt(value: string): string {
  return new Intl.DateTimeFormat('en-GB', {
    day: 'numeric',
    month: 'short',
    hour: '2-digit',
    minute: '2-digit',
  }).format(new Date(value))
}
