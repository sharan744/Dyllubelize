from django.contrib import messages
from django.contrib.auth import update_session_auth_hash
from django.contrib.auth.decorators import login_required
from django.contrib.auth.forms import PasswordChangeForm
from django.shortcuts import render, redirect, get_object_or_404

from core.permissions import role_required
from .forms import UserCreateForm, UserEditForm
from .models import User, Role


@role_required()  # admin only
def user_list(request):
    users = User.objects.all()
    return render(request, "accounts/user_list.html", {
        "users": users, "roles": Role.choices,
    })


@role_required()
def user_create(request):
    if request.method == "POST":
        form = UserCreateForm(request.POST)
        if form.is_valid():
            user = form.save()
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
