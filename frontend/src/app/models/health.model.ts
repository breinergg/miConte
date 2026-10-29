export interface HealthResponse {
  application: string;
  status: 'available';
  version: string;
}

export interface DatabaseHealthResponse {
  application: string;
  status: 'available' | 'degraded';
  database: 'available' | 'unavailable';
}
