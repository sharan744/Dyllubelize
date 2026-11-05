from django.contrib import messages
from django.contrib.auth import update_session_auth_hash
from django.contrib.auth.decorators import login_required
from django.contrib.auth.forms import PasswordChangeForm
from django.shortcuts import render, redirect, get_object_or_404

from core.permissions import role_required
from .forms import UserCreateForm, UserEditForm
from .models import User, Role
from .perms import ACCESS_PERMS, ACCESS_PERM_KEYS, default_perms_for_role


@role_required()  # admin only
def user_list(request):
    users = User.objects.all()
    return render(request, "accounts/user_list.html", {
        "users": users, "roles": Role.choices,
    })


@role_required()  # admin only
def user_access(request):
    """Admin grid to grant/revoke each user's access permissions."""
    users = list(User.objects.all())
    if request.method == "POST":
        changed = 0
        for u in users:
            if u.is_admin_role:
                continue  # admins always have everything
            selected = [p for p in request.POST.getlist(f"perm_{u.id}")
                        if p in ACCESS_PERM_KEYS]
            if list(u.access_perms or []) != selected:
                u.access_perms = selected
                u.save(update_fields=["access_perms"])
                changed += 1
        messages.success(request, f"Access updated for {changed} user(s).")
        return redirect("user_access")
    rows = [{"user": u, "granted": set(u.effective_perms)} for u in users]
    return render(request, "accounts/user_access.html",
                  {"rows": rows, "perms": ACCESS_PERMS})


@role_required()
def user_create(request):
    if request.method == "POST":
        form = UserCreateForm(request.POST)
        if form.is_valid():
            user = form.save()
            # Seed the new user with the default permissions for their role;
            # the admin can fine-tune them on the User Access screen.
            user.access_perms = default_perms_for_role(user.role)
            user.save(update_fields=["access_perms"])
            messages.success(request, f"User “{user.display_name}” created.")
            return redirect("user_list")
    else:
        form = UserCreateForm()
    return render(request, "accounts/user_form.html", {"form": form, "title": "Add User"})


@role_required()
def user_edit(request, pk):
    user = get_object_or_404(User, pk=pk)
    if request.method == "POST":
        form = UserEditForm(request.POST, instance=user)
        if form.is_valid():
            form.save()
            messages.success(request, "User updated.")
            return redirect("user_list")
    else:
        form = UserEditForm(instance=user)
    return render(request, "accounts/user_form.html",
                  {"form": form, "title": f"Edit {user.display_name}", "obj": user})


@login_required
def profile(request):
    if request.method == "POST":
        form = PasswordChangeForm(request.user, request.POST)
        if form.is_valid():
            user = form.save()
            update_session_auth_hash(request, user)
            messages.success(request, "Password changed.")
            return redirect("profile")
    else:
        form = PasswordChangeForm(request.user)
    return render(request, "accounts/profile.html", {"form": form})
