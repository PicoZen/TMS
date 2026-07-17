import pytest
from httpx import AsyncClient


class TestAuth:
    @pytest.mark.asyncio
    async def test_register(self, client: AsyncClient):
        response = await client.post(
            "/api/v1/auth/register",
            json={"email": "newuser@example.com", "password": "password123", "role": "AGENT"},
        )
        assert response.status_code == 201
        data = response.json()
        assert data["email"] == "newuser@example.com"
        assert data["role"] == "AGENT"
        assert "id" in data

    @pytest.mark.asyncio
    async def test_register_duplicate_email(self, client: AsyncClient, test_user):
        response = await client.post(
            "/api/v1/auth/register",
            json={"email": "test@example.com", "password": "password123", "role": "AGENT"},
        )
        assert response.status_code == 409

    @pytest.mark.asyncio
    async def test_login(self, client: AsyncClient, test_user):
        response = await client.post(
            "/api/v1/auth/login",
            json={"email": "test@example.com", "password": "testpassword"},
        )
        assert response.status_code == 200
        data = response.json()
        assert "access_token" in data
        assert "refresh_token" in data
        assert data["token_type"] == "bearer"

    @pytest.mark.asyncio
    async def test_login_invalid_credentials(self, client: AsyncClient, test_user):
        response = await client.post(
            "/api/v1/auth/login",
            json={"email": "test@example.com", "password": "wrongpassword"},
        )
        assert response.status_code == 401

    @pytest.mark.asyncio
    async def test_refresh_token(self, client: AsyncClient, test_user):
        login_response = await client.post(
            "/api/v1/auth/login",
            json={"email": "test@example.com", "password": "testpassword"},
        )
        refresh_token = login_response.json()["refresh_token"]

        response = await client.post(
            "/api/v1/auth/refresh", json={"refresh_token": refresh_token}
        )
        assert response.status_code == 200
        data = response.json()
        assert "access_token" in data
        assert "refresh_token" in data

    @pytest.mark.asyncio
    async def test_get_me(self, client: AsyncClient, auth_headers):
        response = await client.get("/api/v1/auth/me", headers=auth_headers)
        assert response.status_code == 200
        data = response.json()
        assert data["email"] == "test@example.com"
        assert data["role"] == "AGENT"

    @pytest.mark.asyncio
    async def test_unauthorized_without_token(self, client: AsyncClient):
        response = await client.get("/api/v1/auth/me")
        assert response.status_code == 401

    @pytest.mark.asyncio
    async def test_logout(self, client: AsyncClient, test_user):
        login_response = await client.post(
            "/api/v1/auth/login",
            json={"email": "test@example.com", "password": "testpassword"},
        )
        refresh_token = login_response.json()["refresh_token"]

        response = await client.post(
            "/api/v1/auth/logout", json={"refresh_token": refresh_token}
        )
        assert response.status_code == 200

    @pytest.mark.asyncio
    async def test_admin_only_endpoint(self, client: AsyncClient, admin_headers):
        response = await client.get("/api/v1/auth/admin/users", headers=admin_headers)
        assert response.status_code == 200

    @pytest.mark.asyncio
    async def test_agent_cannot_access_admin_endpoint(self, client: AsyncClient, auth_headers):
        response = await client.get("/api/v1/auth/admin/users", headers=auth_headers)
        assert response.status_code == 403