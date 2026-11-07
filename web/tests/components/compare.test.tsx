// Sector comparison: the #compare/ address, the shared pick list and the page.
import { afterEach, describe, expect, it } from 'vitest';
import { screen } from '@testing-library/react';
import { compareFromHash, compareHref } from '@/app/navigation';
import { compareStore } from '@/app/research/compare-store';
import { CompareView } from '@/app/views/CompareView';
import { baseReplies, renderPage, report, sector } from './harness';

afterEach(() => {
  location.hash = '';
  compareStore.clear();
});

describe('compare address and pick list', () => {
  it('keeps order, drops duplicates and keeps at most four', () => {
    expect(compareFromHash('#compare/a,b,a,c,d,e')).toEqual(['a', 'b', 'c', 'd']);
    expect(compareFromHash('#sector/a')).toEqual([]);
    expect(compareFromHash(compareHref(['半导体', 'b']))).toEqual(['半导体', 'b']);
  });

  it('refuses a fifth sector instead of dropping one silently', () => {
    for (const id of ['a', 'b', 'c', 'd']) expect(compareStore.add(id)).toBe(true);
    expect(compareStore.add('e')).toBe(false);
    expect(compareStore.get()).toEqual(['a', 'b', 'c', 'd']);
    compareStore.remove('b');
    expect(compareStore.get()).toEqual(['a', 'c', 'd']);
  });
});

describe('compare page', () => {
  const value = report([
    sector({ metrics: { return_20d: 12.5, history_date: '2026-11-04' } }),
    sector({ id: 'liquor', title: '白酒', score: 41.1, change_pct: -0.8, quote: { change_pct: -0.8 } }),
  ]);

  it('puts the chosen sectors side by side with signed changes and the score note', async () => {
    location.hash = compareHref(['semiconductor', 'liquor']);
    const { container } = renderPage(<CompareView />, { replies: baseReplies({}, value) });
    expect(await screen.findByRole('heading', { name: '板块对比' })).toBeTruthy();
    expect(screen.getByRole('link', { name: '半导体' }).getAttribute('href')).toBe('#sector/semiconductor');
    expect(screen.getByRole('link', { name: '白酒' })).toBeTruthy();
    expect(screen.getByText('+1.25%').className).toContain('text-rise');
    expect(screen.getByText('-0.80%').className).toContain('text-fall');
    expect(screen.getByText('+12.50%')).toBeTruthy();
    expect(container.textContent).toContain('不代表收益概率，不构成投资建议');
    // Neither test sector has its own sample index, so no line is drawn and that is said.
    expect(container.textContent).toContain('没有独立样本指标');
  });

  it('explains unknown sectors and asks for at least two', async () => {
    location.hash = compareHref(['semiconductor', 'nope']);
    renderPage(<CompareView />, { replies: baseReplies({}, value) });
    expect(await screen.findByText(/已略过：nope/)).toBeTruthy();
    expect(screen.getByText(/至少需要 2 个板块才能对比/)).toBeTruthy();
  });
});
