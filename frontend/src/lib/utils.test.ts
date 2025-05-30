import { describe, it, expect } from 'vitest';
import { cn } from './utils';

describe('cn utility', () => {
  it('should merge class names correctly', () => {
    expect(cn('base', 'additional')).toBe('base additional');
  });

  it('should handle conditional classes', () => {
    expect(cn('base', { conditional: true, hidden: false })).toBe('base conditional');
  });

  it('should handle undefined and null values', () => {
    expect(cn('base', undefined, null, 'valid')).toBe('base valid');
  });
}); 