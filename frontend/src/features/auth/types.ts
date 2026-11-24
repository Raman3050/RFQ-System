export type Role = 'BUYER' | 'SUPPLIER' | 'ADMIN';

export interface User {
  id: string;
  email: string;
  full_name: string;
  company_name: string;
  role: Role;
  is_active: boolean;
  created_at: string;
}

export interface AuthResponse {
  access_token: string;
  token_type: 'bearer';
  expires_in: number;
  user: User;
}

export interface LoginInput {
  email: string;
  password: string;
}

/** Public sign-up creates a BUYER. Suppliers join only through an emailed invite. */
export interface RegisterInput extends LoginInput {
  full_name: string;
  company_name: string;
}

export interface AcceptInviteInput {
  token: string;
  password: string;
  full_name: string;
  company_name: string;
}

export const ROLE_LABEL: Record<Role, string> = {
  BUYER: 'Buyer',
  SUPPLIER: 'Supplier',
  ADMIN: 'Admin',
};
