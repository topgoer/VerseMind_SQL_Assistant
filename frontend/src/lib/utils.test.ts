import { describe, it, expect } from 'vitest';
import { cn } from './utils';

describe('cn utility', () => {
  it('should merge class names correctly', () => {
    const result = cn('base', 'additional');
    expect(result).toBe('base additional');
  });

  it('should handle conditional classes', () => {
    const result = cn('base', { conditional: true, hidden: false });
    expect(result).toBe('base conditional');
  });

  it('should handle undefined and null values', () => {
    const result = cn('base', undefined, null, 'valid');
    expect(result).toBe('base valid');
  });
}); 