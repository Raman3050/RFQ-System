import { z } from 'zod';

/** Mirrors backend rules in app/schemas/auth.py so users get instant feedback. */
export const loginSchema = z.object({
  email: z.email('Enter a valid email address'),
  password: z.string().min(1, 'Enter your password').max(128),
});

export const registerSchema = z.object({
  full_name: z.string().trim().min(1, 'Enter your name').max(120),
  company_name: z.string().trim().min(1, 'Enter your company').max(160),
  email: z.email('Enter a valid email address'),
  password: z
    .string()
    .min(8, 'At least 8 characters')
    .max(128, 'At most 128 characters')
    .regex(/[A-Za-z]/, 'Include at least one letter')
    .regex(/\d/, 'Include at least one digit'),
  role: z.enum(['BUYER', 'SUPPLIER']),
});

export type LoginForm = z.infer<typeof loginSchema>;
export type RegisterForm = z.infer<typeof registerSchema>;
