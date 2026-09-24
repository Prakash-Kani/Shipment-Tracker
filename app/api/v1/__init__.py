from fastapi import APIRouter

# from .endpoints import auth, users, admin,  menu_permissions, menus,  button_permissions, buttons, roles, user_management, impersonate
from .endpoints import tracker, tracker_twilio
# # EXAM CRUD
# from .endpoints import subjects, exam_sesssion, paper, mcq_question, mcq_answer, mock, evaluate


api_router = APIRouter()  # Main V1 router

# # Include sub-routers
# api_router.include_router(auth.router, prefix="/auth", tags=["auth"])
# api_router.include_router(impersonate.router, prefix="/impersonate", tags=["Impersonate"], include_in_schema= False)
# api_router.include_router(users.router, prefix="/users", tags=["users"])
# api_router.include_router(user_management.router, prefix="/user", tags=["User Management"])
# api_router.include_router(roles.router, prefix="/roles", tags=["roles"])
# api_router.include_router(menus.router, prefix="/menus", tags=["menus"])
# api_router.include_router(buttons.router, prefix="/buttons", tags=["buttons"])
# api_router.include_router(button_permissions.router, prefix="/button-permissions", tags=["button_permissions"])
# api_router.include_router(menu_permissions.router, prefix="/menu-permissions", tags=["menu_permissions"])
# api_router.include_router(admin.router, prefix="/admin", tags=["admin"])

# api_router.include_router(generate_stream.router, prefix="/generate/stream", tags=["generate Descriptions"])
api_router.include_router(tracker.router, prefix="/whatsapp", tags=["Whatsapp Webhook"])

api_router.include_router(tracker_twilio.router, prefix="/twilio", tags=["Whatsapp Webhook"])

# Export for parent import
__all__ = ["api_router"]