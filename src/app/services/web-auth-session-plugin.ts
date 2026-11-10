import { registerPlugin } from '@capacitor/core';

// Plugin natif iOS local : ios/App/App/WebAuthSessionPlugin.swift
// (ASWebAuthenticationSession). Ouvre une URL OAuth dans la feuille système et
// résout avec l'URL de redirection finale (schéma callbackScheme).
// Rejets : code 'CANCELED' (feuille fermée par l'utilisateur) ou 'FAILED'.
export interface WebAuthSessionPlugin {
  start(options: { url: string; callbackScheme: string }): Promise<{ url: string }>;
}

export const WebAuthSession = registerPlugin<WebAuthSessionPlugin>('WebAuthSession');
