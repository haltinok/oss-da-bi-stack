// The words of the admin console (/admin/), English and Turkish.
const EN = {
  title: "Admin", home: "Dashboards", users: "Users", groups: "Groups", notAdmin: "Only an admin can use this page.", signedOut: "Signing in…",
  search: "Search people", allRoles: "Any role", allGroups: "Any group", allStatus: "Any status", active: "Active", inactive: "Inactive", newUser: "New user",
  username: "Username", name: "Name", email: "Email", role: "Role", status: "Status", firstName: "First name", lastName: "Last name", groupsLabel: "Groups", none: "none",
  edit: "Edit", deactivate: "Deactivate", activate: "Activate", password: "Password", delete: "Delete", actions: "Actions", total: (n) => `${n} ${n === 1 ? "person" : "people"}`,
  createUser: "Create user", saveUser: "Save", cancel: "Cancel", close: "Close", tempPassword: "Temporary password", mustChange: "The person must change it at the first sign-in",
  tempNote: "Choose a password of at least 10 characters. The person is asked to change it at the first sign-in.",
  setPassword: "Set password", newPassword: "New password", keep: "Ask the person to change it at the next sign-in", setIt: "Set password",
  reset: "Reset password", resetTitle: "Reset password", resetBy: "How should the person get a new password?", resetTemp: "Make a temporary password (shown once)", resetEmail: "Email Keycloak's update-password link",
  resetDone: "Temporary password for", resetShown: "Shown once. Give it to the person; they must change it at the next sign-in.", emailed: "The email was sent.",
  deleteTitle: "Delete this person?", deleteWhy: "Deactivating keeps their dashboards and history and ends their access; deleting cannot be undone.", deleteType: "Type the username to confirm", deleteIt: "Delete",
  deactivateTitle: "Deactivate this person?", deactivateWhy: "They are signed out and cannot sign in again until you activate them. Access already issued to their browser ends within a few minutes.",
  newGroup: "New group", groupName: "Group name", create: "Create", rename: "Rename", members: "Members", membersOf: (g) => `Members of ${g}`, addMember: "Add a person", add: "Add", remove: "Remove",
  deleteGroup: "Delete this group?", deleteGroupWhy: "The people in it stay; they just leave the group.", noUsers: "Nobody matches.", noGroups: "No groups yet.", noMembers: "Nobody is in this group.",
  shortPassword: "The password needs at least 10 characters.", saved: "Saved.", failed: "Could not do that:", you: "you", rolesHint: { admin: "everything, and this console", manager: "sales, by territory", rep: "sales, own territory, no profit", purchasing: "inventory", marketing: "inventory, no supplier data" },
};
const TR = {
  title: "Yönetim", home: "Panolar", users: "Kullanıcılar", groups: "Gruplar", notAdmin: "Bu sayfayı yalnızca yönetici kullanabilir.", signedOut: "Giriş yapılıyor…",
  search: "Kişi ara", allRoles: "Tüm roller", allGroups: "Tüm gruplar", allStatus: "Tüm durumlar", active: "Etkin", inactive: "Devre dışı", newUser: "Yeni kullanıcı",
  username: "Kullanıcı adı", name: "Ad", email: "E-posta", role: "Rol", status: "Durum", firstName: "Ad", lastName: "Soyad", groupsLabel: "Gruplar", none: "yok",
  edit: "Düzenle", deactivate: "Devre dışı bırak", activate: "Etkinleştir", password: "Parola", delete: "Sil", actions: "İşlemler", total: (n) => `${n} kişi`,
  createUser: "Kullanıcı oluştur", saveUser: "Kaydet", cancel: "Vazgeç", close: "Kapat", tempPassword: "Geçici parola", mustChange: "Kişi ilk girişte değiştirmek zorundadır",
  tempNote: "En az 10 karakterli bir parola seçin. Kişiden ilk girişte değiştirmesi istenir.",
  setPassword: "Parola belirle", newPassword: "Yeni parola", keep: "Sonraki girişte değiştirmesi istensin", setIt: "Parolayı belirle",
  reset: "Parolayı sıfırla", resetTitle: "Parolayı sıfırla", resetBy: "Kişi yeni parolayı nasıl alsın?", resetTemp: "Geçici parola üret (bir kez gösterilir)", resetEmail: "Keycloak'un parola yenileme bağlantısını e-postayla gönder",
  resetDone: "Geçici parola:", resetShown: "Yalnızca bir kez gösterilir. Kişiye iletin; sonraki girişte değiştirmek zorundadır.", emailed: "E-posta gönderildi.",
  deleteTitle: "Bu kişi silinsin mi?", deleteWhy: "Devre dışı bırakmak panolarını ve geçmişini korur ve erişimi keser; silme geri alınamaz.", deleteType: "Onaylamak için kullanıcı adını yazın", deleteIt: "Sil",
  deactivateTitle: "Bu kişi devre dışı bırakılsın mı?", deactivateWhy: "Oturumu kapatılır ve siz etkinleştirene kadar giriş yapamaz. Tarayıcısına verilmiş erişim birkaç dakika içinde biter.",
  newGroup: "Yeni grup", groupName: "Grup adı", create: "Oluştur", rename: "Yeniden adlandır", members: "Üyeler", membersOf: (g) => `${g} grubunun üyeleri`, addMember: "Kişi ekle", add: "Ekle", remove: "Çıkar",
  deleteGroup: "Bu grup silinsin mi?", deleteGroupWhy: "İçindeki kişiler kalır; yalnızca gruptan çıkarlar.", noUsers: "Eşleşen kimse yok.", noGroups: "Henüz grup yok.", noMembers: "Bu grupta kimse yok.",
  shortPassword: "Parola en az 10 karakter olmalı.", saved: "Kaydedildi.", failed: "Yapılamadı:", you: "siz", rolesHint: { admin: "her şey ve bu sayfa", manager: "satış, bölgeye göre", rep: "satış, kendi bölgesi, kâr yok", purchasing: "envanter", marketing: "envanter, tedarikçi verisi yok" },
};
export const adminStrings = (lang) => ({ ...EN, ...(lang === "tr" ? TR : {}) });
