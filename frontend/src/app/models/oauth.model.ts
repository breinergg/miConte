export interface AuthorizeResponse {
  authorization_url: string;
  state: string;
}

export interface ConnectionStatusResponse {
  is_connected: boolean;
  external_channel_id: string;
  is_active: boolean;
  granted_scopes: string;
  token_expires_at: string | null;
}

export interface DisconnectResponse {
  channel_id: string;
  local_disconnected: boolean;
  remote_revoked: boolean;
  details: string;
}
