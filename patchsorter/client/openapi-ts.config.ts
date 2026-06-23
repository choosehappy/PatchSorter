import { defineConfig } from '@hey-api/openapi-ts';
import { SERVER_URL } from './config.ts';

export default defineConfig({
  input: `${SERVER_URL}/openapi.json`,
  output: 'src/api_client',
});