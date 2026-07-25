# Publish AetherStack to the VS Code Marketplace

Official docs: [Publishing Extensions](https://code.visualstudio.com/api/working-with-extensions/publishing-extension)

Extension id will be: **`AetherStack.aetherstack`**  
Listing: https://marketplace.visualstudio.com/items?itemName=AetherStack.aetherstack

Source: [`integrations/vscode/`](../integrations/vscode/)

---

## Prerequisites

- Node.js + npm  
- `@vscode/vsce` (`npm install -g @vscode/vsce`)  
- A **Microsoft account** (same one for Azure DevOps + Marketplace)  
- Publisher id **exactly** `AetherStack` (matches `package.json` → `"publisher": "AetherStack"`)

---

## 1. Create Azure DevOps organization (if you have none)

1. Open https://dev.azure.com/  
2. Sign in with Microsoft.  
3. Create an organization if prompted (any name is fine; used only for tokens).

## 2. Create a Personal Access Token (PAT)

1. Open https://dev.azure.com/ → user icon → **Personal access tokens**  
   Direct pattern: `https://dev.azure.com/<YOUR_ORG>/_usersSettings/tokens`  
2. **+ New Token**  
3. Settings:

| Field | Value |
|-------|--------|
| Name | `vsce-aetherstack` |
| Organization | All accessible organizations |
| Expiration | 30–90 days (or custom) |
| Scopes | **Custom defined** → expand **Marketplace** → check **Manage** |

4. **Create** → **copy the token once** (you will not see it again).

> Alternative (sometimes easier): Marketplace publisher page → **Security** / PAT links if shown for your account.

## 3. Create the Marketplace publisher

1. Open https://marketplace.visualstudio.com/manage  
2. Sign in with the **same** Microsoft account as the PAT.  
3. **Create publisher** (left pane).  
4. Set:

| Field | Value |
|-------|--------|
| **ID** | `AetherStack` (must match `package.json`) |
| **Name** | `AetherStack` (display name) |

5. Save. Confirm the publisher appears in the manage list.

If `AetherStack` is taken, either:

- Use the existing publisher you control, or  
- Create another id and change `"publisher"` in `integrations/vscode/package.json` before publish.

## 4. Login + publish (local machine)

```powershell
cd path\to\aetherstack\integrations\vscode

# One-time login (stores PAT for publisher AetherStack)
vsce login AetherStack
# Paste PAT when prompted (input is hidden)

# Publish current package.json version (e.g. 0.1.0)
vsce publish
```

Or without interactive login:

```powershell
cd path\to\aetherstack\integrations\vscode
$env:VSCE_PAT = "PASTE_PAT_HERE"   # do not commit this
vsce publish
# clear when done:
Remove-Item Env:VSCE_PAT
```

Or pass the token once:

```powershell
vsce publish -p YOUR_PAT_HERE
```

### Version bump

```powershell
vsce publish patch   # 0.1.0 → 0.1.1
# or: vsce publish minor / major
```

### Package only (no upload)

```powershell
vsce package
# → aetherstack-0.1.0.vsix
```

---

## 5. Verify

1. https://marketplace.visualstudio.com/manage — extension listed under publisher **AetherStack**  
2. Public page (may take a few minutes):  
   https://marketplace.visualstudio.com/items?itemName=AetherStack.aetherstack  
3. Install:

```bash
code --install-extension AetherStack.aetherstack
```

Help for users: [VSCODE-EXTENSION.md](./VSCODE-EXTENSION.md)

---

## Common errors

| Error | Fix |
|-------|-----|
| `Publisher 'AetherStack' not found` | Create publisher with **exact** id `AetherStack` on the manage site |
| `Unauthorized` / `401` | PAT expired, wrong account, or missing **Marketplace → Manage** |
| `The Personal Access Token is invalid` | Recreate PAT with **All accessible organizations** + Marketplace Manage |
| `Extension already exists` / version conflict | Bump `version` in `package.json` or `vsce publish patch` |
| `Invalid publisher name` | Publisher id must match package.json case-sensitively |
| Icon / README validation failed | Ensure `media/icon.png` ≥ 128×128; README has no broken relative links in VSIX |

---

## Security

- Never commit the PAT to git or put it in the repo.  
- Prefer env `VSCE_PAT` in a private shell, then unset.  
- Rotate the PAT after publish if the shell history is shared.  
- CI: store PAT as GitHub Actions secret `VSCE_PAT` when publishing from Actions.

---

## Checklist

- [ ] Azure DevOps org exists  
- [ ] PAT with **Marketplace → Manage** created  
- [ ] Publisher **AetherStack** on marketplace.visualstudio.com/manage  
- [ ] `cd integrations/vscode`  
- [ ] `vsce login AetherStack` (or `VSCE_PAT`)  
- [ ] `vsce publish`  
- [ ] Listing visible; `code --install-extension AetherStack.aetherstack` works  
